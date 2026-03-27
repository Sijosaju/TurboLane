"""
turbolane/engine.py

TurboLaneEngine is the single public entry point for the TurboLane SDK.

Supported modes:
    edge       -> EdgePolicy
    federated  -> FederatedPolicy
    client     -> alias of edge (backward compatibility)

Supported algorithms:
    qlearning
    ppo

Metric collection modes:
    1. Auto (socket-based) — attach real TCP sockets, engine reads metrics
       automatically from the OS TCP stack. Most accurate.

    2. Manual report — call engine.report_metrics(...) with your own values.
       Useful when sockets are not accessible (e.g. library hides them).

    3. Legacy passthrough — pass metrics directly to decide()/learn().
       100% backward compatible with v1.0.0 API.
"""

import logging
import socket as _socket_module
from typing import List, Optional

logger = logging.getLogger(__name__)

_VALID_ALGORITHMS = {"qlearning", "ppo"}
_MODE_ALIASES = {
    "client": "edge",
}
_VALID_MODES = {"edge", "federated"}


class TurboLaneEngine:
    """
    Unified TurboLane engine with automatic metric collection.

    Metric collection options (choose one):

    Option 1 — Automatic from sockets (most accurate):
        engine = TurboLaneEngine(mode="edge")
        engine.attach_sockets([sock1, sock2, ...])
        engine.report_bytes(total_bytes_this_interval)
        streams = engine.decide()     # no args
        engine.learn()                # no args

    Option 2 — Manual metric report:
        engine = TurboLaneEngine(mode="edge")
        engine.report_metrics(throughput_mbps=45.0, rtt_ms=32.0, loss_pct=0.1)
        streams = engine.decide()
        engine.learn()

    Option 3 — Legacy passthrough (v1.0.0 compatible, zero changes needed):
        engine = TurboLaneEngine(mode="edge")
        streams = engine.decide(throughput_mbps=45.0, rtt_ms=32.0, loss_pct=0.1)
        engine.learn(throughput_mbps=48.0, rtt_ms=31.0, loss_pct=0.1)

    Public interface:
        attach_sockets(sockets)
        update_sockets(sockets)
        report_bytes(total_bytes)
        report_metrics(throughput_mbps, rtt_ms, loss_pct)
        decide(throughput_mbps=None, rtt_ms=None, loss_pct=None) -> int
        learn(throughput_mbps=None, rtt_ms=None, loss_pct=None)
        save() -> bool
        get_stats() -> dict
        reset()
    """

    # Safe fallback values used when no metrics are available yet
    _FALLBACK_THROUGHPUT = 10.0
    _FALLBACK_RTT        = 50.0
    _FALLBACK_LOSS       = 0.0

    def __init__(
        self,
        mode: str = "edge",
        algorithm: str = "qlearning",
        **policy_kwargs,
    ):
        normalized_mode = self._normalize_mode(mode)
        normalized_algorithm = algorithm.lower().replace("-", "").replace("_", "")

        if normalized_mode not in _VALID_MODES:
            raise ValueError(
                f"Unknown mode '{mode}'. Valid modes: {sorted(_VALID_MODES)} "
                f"(alias: client -> edge)."
            )
        if normalized_algorithm not in _VALID_ALGORITHMS:
            raise ValueError(
                f"Unknown algorithm '{algorithm}'. Valid algorithms: {sorted(_VALID_ALGORITHMS)}"
            )

        self.mode = normalized_mode
        self.algorithm = normalized_algorithm
        self._policy = self._build_policy(self.mode, policy_kwargs)

        self._reader = None
        self._reported_metrics = {}
        self._metric_source = "none"

        logger.info(
            "TurboLaneEngine ready: mode=%s algorithm=%s",
            self.mode,
            self.algorithm,
        )

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        mode_key = mode.lower().strip().replace("-", "_")
        return _MODE_ALIASES.get(mode_key, mode_key)

    # -----------------------------------------------------------------------
    # Option 1: Socket-based automatic collection
    # -----------------------------------------------------------------------

    def attach_sockets(self, sockets: List[_socket_module.socket]) -> None:
        """
        Attach active TCP sockets for automatic metric collection.

        Call this after opening your parallel transfer sockets.
        Engine reads throughput, RTT, and packet loss from OS TCP stack.

        Args:
            sockets: list of active, connected socket.socket objects
        """
        if not sockets:
            logger.warning("attach_sockets: empty socket list — no-op")
            return

        from turbolane.probe import TCPSocketReader
        if self._reader is None:
            self._reader = TCPSocketReader(sockets)
        else:
            self._reader.update_sockets(sockets)

        self._metric_source = "socket"
        logger.info(
            "TurboLaneEngine: attached %d sockets via %s",
            len(sockets),
            self._reader.reader_type,
        )

    def update_sockets(self, sockets: List[_socket_module.socket]) -> None:
        """
        Update tracked sockets when stream count changes.
        Preserves retransmission counters for sockets still in the list.
        """
        self.attach_sockets(sockets)

    def report_bytes(self, total_bytes: int) -> None:
        """
        Report total bytes transferred across all sockets since last call.

        Call this at the end of each transfer interval before decide()/learn().
        Used by the engine to compute aggregate throughput.

        Args:
            total_bytes: bytes transferred across ALL parallel streams
                         since the last call to report_bytes()
        """
        if self._reader is None:
            logger.debug("report_bytes: no sockets attached yet")
            return
        self._reader.report_bytes_all(total_bytes)

    # -----------------------------------------------------------------------
    # Option 2: Manual metric report
    # -----------------------------------------------------------------------

    def report_metrics(
        self,
        throughput_mbps: float,
        rtt_ms: float,
        loss_pct: float,
    ) -> None:
        """
        Manually report current network metrics.

        Use when you measure metrics yourself but cannot expose sockets.
        After calling this, decide() and learn() work with no args.

        Args:
            throughput_mbps: aggregate transfer speed in Mbps
            rtt_ms:          round-trip time in milliseconds
            loss_pct:        packet loss percentage (0.0 - 100.0)
        """
        self._reported_metrics = {
            "throughput_mbps": float(throughput_mbps),
            "rtt_ms": float(rtt_ms),
            "loss_pct": float(loss_pct),
        }
        if self._metric_source != "socket":
            self._metric_source = "manual"

    # -----------------------------------------------------------------------
    # Internal: metric resolution
    # -----------------------------------------------------------------------

    def _resolve_metrics(
        self,
        throughput_mbps: Optional[float],
        rtt_ms: Optional[float],
        loss_pct: Optional[float],
    ) -> tuple:
        """
        Resolve which metrics to use. Priority order:
            1. Explicit args (legacy passthrough)
            2. Socket-based auto-collection
            3. Manually reported metrics
            4. Safe fallback defaults
        """
        # Priority 1: explicit args
        if throughput_mbps is not None and rtt_ms is not None and loss_pct is not None:
            return float(throughput_mbps), float(rtt_ms), float(loss_pct)

        # Priority 2: socket-based
        if self._reader is not None and self._metric_source == "socket":
            snapshot = self._reader.read()
            if snapshot.valid:
                logger.debug(
                    "Metrics from socket: tput=%.2f rtt=%.1f loss=%.4f",
                    snapshot.throughput_mbps, snapshot.rtt_ms, snapshot.loss_pct,
                )
                return snapshot.throughput_mbps, snapshot.rtt_ms, snapshot.loss_pct
            logger.debug("Socket snapshot not valid yet — trying next source")

        # Priority 3: manually reported
        if self._reported_metrics:
            m = self._reported_metrics
            return m["throughput_mbps"], m["rtt_ms"], m["loss_pct"]

        # Priority 4: safe defaults
        logger.debug(
            "No metrics available — using safe defaults. "
            "Call attach_sockets() or report_metrics() first."
        )
        return self._FALLBACK_THROUGHPUT, self._FALLBACK_RTT, self._FALLBACK_LOSS

    # -----------------------------------------------------------------------
    # Core interface
    # -----------------------------------------------------------------------

    def decide(
        self,
        throughput_mbps: Optional[float] = None,
        rtt_ms: Optional[float] = None,
        loss_pct: Optional[float] = None,
    ) -> int:
        """
        Return a stream-count recommendation for current network conditions.

        Zero-arg usage (with sockets attached or metrics reported):
            streams = engine.decide()

        Legacy usage (explicit metrics):
            streams = engine.decide(throughput_mbps=45.0, rtt_ms=32.0, loss_pct=0.1)
        """
        t, r, l = self._resolve_metrics(throughput_mbps, rtt_ms, loss_pct)
        return self._policy.decide(t, r, l)

    def learn(
        self,
        throughput_mbps: Optional[float] = None,
        rtt_ms: Optional[float] = None,
        loss_pct: Optional[float] = None,
    ) -> None:
        """
        Update policy from metrics observed after the previous decision.

        Zero-arg usage (with sockets attached or metrics reported):
            engine.learn()

        Legacy usage (explicit metrics):
            engine.learn(throughput_mbps=48.0, rtt_ms=31.0, loss_pct=0.1)
        """
        t, r, l = self._resolve_metrics(throughput_mbps, rtt_ms, loss_pct)
        self._policy.learn(t, r, l)

    def save(self) -> bool:
        """Persist the policy state to disk."""
        return self._policy.save()

    def get_stats(self) -> dict:
        """Return policy, engine, and metric collection stats."""
        stats = self._policy.get_stats()
        stats["engine_mode"] = self.mode
        stats["engine_algorithm"] = self.algorithm
        stats["metric_source"] = self._metric_source

        if self._reader is not None:
            stats["probe_os"] = self._reader.os_name
            stats["probe_reader"] = self._reader.reader_type
            stats["probe_socket_count"] = self._reader.socket_count

        return stats

    def reset(self) -> None:
        """Clear learned policy state in memory."""
        self._policy.reset()

    # -----------------------------------------------------------------------
    # Convenience properties
    # -----------------------------------------------------------------------

    @property
    def current_connections(self) -> int:
        """Current recommended stream count."""
        return self._policy.current_connections

    @property
    def metric_source(self) -> str:
        """Active metric source: 'socket', 'manual', or 'none'."""
        return self._metric_source

    # -----------------------------------------------------------------------
    # Internal policy factory
    # -----------------------------------------------------------------------

    def _build_policy(self, mode: str, kwargs: dict):
        if mode == "edge":
            from turbolane.policies.edge import EdgePolicy
            return EdgePolicy(**kwargs)
        if mode == "federated":
            from turbolane.policies.federated import FederatedPolicy
            return FederatedPolicy(**kwargs)
        raise ValueError(f"Unknown mode: {mode}")

    def __repr__(self) -> str:
        return (
            f"TurboLaneEngine("
            f"mode={self.mode!r}, "
            f"algorithm={self.algorithm!r}, "
            f"connections={self.current_connections}, "
            f"metric_source={self._metric_source!r})"
        )
