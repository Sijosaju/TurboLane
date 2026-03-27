"""
Q-table persistence with atomic writes and optional packaged seed loading.
"""

from importlib import resources
import json
import logging
from pathlib import Path
import time

from platformdirs import user_data_dir

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"
_APP_NAME = "TurboLane"
_APP_AUTHOR = False


class QTableStorage:
    """
    Handles Q-table loading and saving with configurable path and atomic writes.

    Usage:
        storage = QTableStorage(profile="edge")
        Q, meta = storage.load()
        storage.save(Q, stats)
    """

    def __init__(
        self,
        model_dir: str | None = None,
        table_filename: str = "q_table.json",
        backup_filename: str = "q_table.backup.json",
        profile: str = "edge",
        seed_from_package: bool = True,
    ):
        model_path = Path(model_dir).expanduser() if model_dir else self._default_model_dir(profile)
        try:
            model_path.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            if model_dir is not None:
                raise
            fallback = Path.cwd() / ".turbolane" / "models" / profile
            fallback.mkdir(parents=True, exist_ok=True)
            logger.warning(
                "Default model directory '%s' not writable (%s). Falling back to '%s'.",
                model_path,
                exc,
                fallback,
            )
            model_path = fallback

        self.model_dir = str(model_path)
        self.table_path = model_path / table_filename
        self.backup_path = model_path / backup_filename
        self._tmp_path = model_path / f"{table_filename}.tmp"

        if seed_from_package and not self.table_path.exists():
            self._seed_from_package(profile=profile, table_filename=table_filename)

        logger.info("QTableStorage ready: %s", self.table_path)

    def _default_model_dir(self, profile: str) -> Path:
        base = Path(user_data_dir(_APP_NAME, _APP_AUTHOR))
        return base / "models" / profile

    def _seed_from_package(self, profile: str, table_filename: str) -> None:
        """
        Seed a baseline Q-table from packaged data if available.
        """
        try:
            data_root = resources.files(f"turbolane.data.{profile}")
            seed_path = data_root / table_filename
            if seed_path.is_file():
                with seed_path.open("rb") as src, self.table_path.open("wb") as dst:
                    dst.write(src.read())
                logger.info("Q-table seeded from package data -> %s", self.table_path)
        except ModuleNotFoundError:
            logger.info("No packaged seed module for profile '%s'; starting fresh", profile)
        except FileNotFoundError:
            logger.info("No packaged seed file for profile '%s'; starting fresh", profile)
        except Exception as exc:
            logger.warning("Could not seed packaged Q-table for profile '%s': %s", profile, exc)

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------

    def save(self, Q: dict, stats: dict) -> bool:
        """
        Persist Q-table and agent stats to disk.

        Returns:
            True on success, False on failure (never raises).
        """
        try:
            serialized_q = {
                str(state): {str(a): q for a, q in actions.items()}
                for state, actions in Q.items()
            }

            payload = {
                "schema_version": SCHEMA_VERSION,
                "saved_at": time.time(),
                "saved_at_human": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                "q_table": serialized_q,
                "stats": stats,
            }

            with self._tmp_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

            if self.table_path.exists():
                self.table_path.unlink()

            self._tmp_path.replace(self.table_path)

            logger.info("Q-table saved: %d states -> %s", len(Q), self.table_path)
            return True

        except Exception as exc:
            logger.error("Failed to save Q-table: %s", exc)
            if self._tmp_path.exists():
                try:
                    self._tmp_path.unlink()
                except Exception:
                    pass
            return False

    # -----------------------------------------------------------------------
    # Load
    # -----------------------------------------------------------------------

    def load(self) -> tuple[dict, dict]:
        """
        Load Q-table and metadata from disk.

        Returns:
            (Q, metadata) - returns ({}, {}) if no file exists or load fails.
        """
        for path, label in ((self.table_path, "primary"), (self.backup_path, "backup")):
            result = self._try_load(path, label)
            if result is not None:
                if label == "primary" and self.backup_path.exists():
                    self.backup_path.unlink()
                return result

        logger.info("No Q-table found at %s - starting fresh", self.model_dir)
        return {}, {}

    def _try_load(self, path: Path, label: str) -> tuple[dict, dict] | None:
        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)

            raw_q = payload.get("q_table", {})
            metadata = payload.get("stats", {})

            Q: dict[tuple, dict[int, float]] = {}
            for state_str, actions in raw_q.items():
                try:
                    state = tuple(int(x) for x in state_str.strip("()").split(",") if x.strip())
                    Q[state] = {int(a): float(q) for a, q in actions.items()}
                except Exception as parse_err:
                    logger.warning("Skipping malformed state '%s': %s", state_str, parse_err)
                    continue

            logger.info("Q-table loaded (%s): %d states from %s", label, len(Q), path)
            return Q, metadata

        except json.JSONDecodeError as exc:
            logger.warning("Corrupted Q-table at %s: %s", path, exc)
            return None
        except Exception as exc:
            logger.warning("Could not load Q-table from %s: %s", path, exc)
            return None

    # -----------------------------------------------------------------------
    # Utility
    # -----------------------------------------------------------------------

    def exists(self) -> bool:
        """Check if primary Q-table file exists."""
        return self.table_path.exists()

    def delete(self) -> None:
        """Delete all Q-table related files."""
        for path in (self.table_path, self.backup_path, self._tmp_path):
            if path.exists():
                path.unlink()
        logger.info("Q-table files deleted from %s", self.model_dir)

    def __repr__(self) -> str:
        return f"QTableStorage(model_dir={self.model_dir!r}, exists={self.exists()})"
