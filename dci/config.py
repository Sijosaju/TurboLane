"""
DCI Configuration Module
Centralized configuration for inter-site file transfer system.
"""
import os
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
MODEL_DIR = PROJECT_ROOT / "models" / "dci_model"
TRANSFER_ROOT = PROJECT_ROOT / "dci_transfers"

# Network
DEFAULT_SERVER_HOST = "0.0.0.0"
DEFAULT_SERVER_PORT = 9876
MAX_CONNECTIONS = 32
CONNECTION_TIMEOUT = 120

# Transfer
CHUNK_SIZE = 512 * 1024  # 512KB per chunk
DEFAULT_BUFFER_SIZE = 1024 * 1024  # 1MB

# RL
RL_ENABLED = True
RL_INITIAL_STREAMS = 4
RL_MIN_STREAMS = 1
RL_MAX_STREAMS = 16

# Logging
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def initialize_directories():
    """Create necessary directories if they don't exist."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    TRANSFER_ROOT.mkdir(parents=True, exist_ok=True)
    (TRANSFER_ROOT / "incoming").mkdir(exist_ok=True)
    (TRANSFER_ROOT / "completed").mkdir(exist_ok=True)
    (TRANSFER_ROOT / "failed").mkdir(exist_ok=True)


def get_model_path():
    """Get the model directory path as string."""
    return str(MODEL_DIR)