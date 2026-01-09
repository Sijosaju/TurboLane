"""
DCI Configuration Module - Updated with PPO algorithm support
Complete configuration for DCI File Sharing System.
"""
import os
import sys
from pathlib import Path

# ======================== Project Structure ========================
PROJECT_ROOT = Path(__file__).parent.parent
DCI_ROOT = PROJECT_ROOT / "dci"
MODELS_DIR = PROJECT_ROOT / "models" / "dci"
LOGS_DIR = PROJECT_ROOT / "logs" / "dci"
TRANSFER_ROOT = PROJECT_ROOT / "dci_transfers"

# ======================== Network Configuration ========================
DEFAULT_SERVER_HOST = "0.0.0.0"        # Bind to all interfaces
DEFAULT_SERVER_PORT = 9876             # Default port for DCI protocol
MAX_CONNECTIONS = 32                   # Maximum concurrent connections
CONNECTION_TIMEOUT = 120               # Connection timeout in seconds
SOCKET_TIMEOUT = 300                   # Socket timeout in seconds
BACKLOG_SIZE = 10                      # Socket backlog queue size

# Socket options
SO_REUSEADDR = True                    # Allow address reuse
SO_KEEPALIVE = True                    # Enable TCP keepalive
TCP_NODELAY = True                     # Disable Nagle's algorithm

# Windows-specific TCP keepalive settings
TCP_KEEPIDLE = 60                      # Time before sending keepalive probes
TCP_KEEPINTVL = 10                     # Interval between keepalive probes
TCP_KEEPCNT = 5                        # Number of keepalive probes before closing

# ======================== Transfer Configuration ========================
CHUNK_SIZE = 2 * 1024 * 1024           # 2MB per chunk (optimal for 10Gbps links)
DEFAULT_BUFFER_SIZE = 1024 * 1024      # 1MB buffer size for file operations
MAX_CHUNKS_PER_STREAM = 1000           # Maximum chunks per stream
INFLIGHT_WINDOW = 4                    # Number of unacknowledged chunks per stream

# File handling
MAX_FILE_SIZE = 100 * 1024 * 1024 * 1024  # 100GB maximum file size
ALLOWED_EXTENSIONS = []                # Empty list means all extensions allowed
BLOCKED_EXTENSIONS = ['.exe', '.bat', '.sh', '.py']  # Potentially dangerous

# Checksum settings
CHECKSUM_ALGORITHM = "sha256"          # Checksum algorithm
VERIFY_CHECKSUM = True                 # Verify checksum after transfer
CHECKSUM_CHUNK_SIZE = 512 * 1024       # 512KB chunks for checksum calculation

# ======================== RL Configuration ========================
RL_ENABLED = True                      # Enable RL optimization
RL_ALGORITHM = "ppo"                   # Options: "qlearning" or "ppo"
RL_INITIAL_STREAMS = 4                 # Initial number of parallel streams
RL_MIN_STREAMS = 2                     # Minimum parallel streams
RL_MAX_STREAMS = 16                    # Maximum parallel streams
RL_MONITORING_INTERVAL = 5.0           # Monitoring interval in seconds

# ======================== PPO Specific Settings ========================
PPO_STATE_HISTORY_SIZE = 5             # n from paper (bounded history)
PPO_LEARNING_RATE = 0.001              # Adam optimizer learning rate
PPO_GAMMA = 0.99                       # Discount factor
PPO_CLIP_EPSILON = 0.2                 # PPO clipping parameter
PPO_EPOCHS = 10                        # Number of PPO update epochs
PPO_BATCH_SIZE = 64                    # Batch size for training
PPO_HIDDEN_DIM = 64                    # Neural network hidden dimension

# Paper's utility function parameters (Equation 3)
UTILITY_K = 1.02                       # Cost per stream (K)
UTILITY_B = 5.0                        # Punishment coefficient (B)
UTILITY_EPSILON = 0.08                 # 8% relative threshold (ε)

# Action mapping for PPO (paper's action space: -5, -1, 0, +1, +5)
PPO_ACTION_MAP = [-5, -1, 0, +1, +5]

# ======================== Q-Learning Settings (Legacy) ========================
QL_LEARNING_RATE = 0.1                 # α - learning rate
QL_DISCOUNT_FACTOR = 0.8               # γ - discount factor
QL_EXPLORATION_RATE = 0.3              # ε - initial exploration rate
QL_MIN_EXPLORATION = 0.05              # minimum exploration rate
QL_EXPLORATION_DECAY = 0.995           # exploration decay rate

# Q-learning action mapping (legacy: -2, -1, 0, +1, +2)
QL_ACTION_MAP = [-2, -1, 0, +1, +2]

# State discretization levels (for Q-learning only)
THROUGHPUT_LEVELS = 6                  # Very Low, Low, Medium, High, Very High, Excellent
RTT_LEVELS = 4                         # Excellent, Good, Poor, Very Poor
LOSS_LEVELS = 5                        # Excellent, Good, Moderate, Poor, Very Poor

# ======================== Protocol Configuration ========================
PROTOCOL_VERSION = 1
MAGIC_BYTES = b"DCIFILE\x01"
HEADER_SIZE = 14                       # Magic(8) + Version(1) + Type(1) + Length(4)

# Message types
MSG_TRANSFER_REQUEST = 0x01
MSG_TRANSFER_ACCEPT = 0x02
MSG_TRANSFER_REJECT = 0x03
MSG_CHUNK_DATA = 0x04
MSG_TRANSFER_COMPLETE = 0x05
MSG_TRANSFER_ERROR = 0x06
MSG_ACK = 0x07

# Chunk header format: transfer_id(36) + stream_id(4) + offset(8) + data_len(4)
CHUNK_HEADER_SIZE = 52

# ======================== Storage Configuration ========================
# Transfer directory structure
INCOMING_DIR = TRANSFER_ROOT / "incoming"
COMPLETED_DIR = TRANSFER_ROOT / "completed"
FAILED_DIR = TRANSFER_ROOT / "failed"
QUEUED_DIR = TRANSFER_ROOT / "queued"

# File naming
FILE_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
UNIQUE_FILENAME_TEMPLATE = "{stem}_{timestamp}_{id[:8]}{ext}"

# Retention policy
MAX_COMPLETED_FILES = 1000             # Maximum files in completed directory
MAX_FAILED_FILES = 100                 # Maximum files in failed directory
CLEANUP_INTERVAL = 3600                # Cleanup interval in seconds (1 hour)

# ======================== Logging Configuration ========================
LOG_LEVEL = "INFO"                     # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILE = str(LOGS_DIR / "dci.log")
LOG_MAX_SIZE = 10 * 1024 * 1024        # 10MB per log file
LOG_BACKUP_COUNT = 5                   # Number of backup log files

# Component-specific logging
LOG_CLIENT = True
LOG_SERVER = True
LOG_TRANSFER = True
LOG_RL = True
LOG_NETWORK = False
LOG_PROTOCOL = False

# ======================== Security Configuration ========================
ENABLE_AUTHENTICATION = False          # Enable client authentication
ALLOWED_CLIENTS = []                   # List of allowed client IPs (empty = all)
BLOCKED_CLIENTS = []                   # List of blocked client IPs

# Rate limiting
MAX_REQUESTS_PER_MINUTE = 60           # Maximum requests per minute per client
RATE_LIMIT_WINDOW = 60                 # Rate limit window in seconds

# File security
SCAN_FOR_MALWARE = False               # Scan transferred files (requires ClamAV)
MAX_FILENAME_LENGTH = 255              # Maximum filename length
DISALLOW_HIDDEN_FILES = True           # Disallow files starting with '.'

# ======================== Performance Configuration ========================
# Thread pool settings
WORKER_THREADS = 4                     # Number of worker threads
IO_THREADS = 2                         # Number of I/O threads
MAX_WORKER_THREADS = 16                # Maximum worker threads

# Buffering
FILE_BUFFER_SIZE = 16 * 1024 * 1024    # 16MB file buffer for high throughput
SOCKET_BUFFER_SIZE = 1024 * 1024       # 1MB socket buffer

# Monitoring
METRICS_INTERVAL = 5                   # Metrics collection interval in seconds
STATS_INTERVAL = 60                    # Statistics logging interval in seconds
HEALTH_CHECK_INTERVAL = 30             # Health check interval in seconds

# ======================== Model Persistence ========================
MODEL_SAVE_INTERVAL = 50               # Save model every N decisions
MODEL_BACKUP_COUNT = 3                 # Number of model backups to keep
MODEL_COMPRESSION = True               # Compress model files

# Model file names
Q_TABLE_FILE = 'q_table.json'
Q_TABLE_BACKUP = 'q_table_backup.json'
PPO_MODEL_FILE = 'ppo_model.pt'
PPO_METADATA_FILE = 'ppo_metadata.json'

# ======================== Client Configuration ========================
CLIENT_RECONNECT_ATTEMPTS = 3          # Number of reconnect attempts
CLIENT_RECONNECT_DELAY = 2             # Delay between reconnects in seconds
CLIENT_MAX_RETRIES = 3                 # Maximum retries for failed chunks
CLIENT_CHUNK_TIMEOUT = 30              # Chunk transfer timeout in seconds

# ======================== Server Configuration ========================
SERVER_SHUTDOWN_TIMEOUT = 30           # Graceful shutdown timeout in seconds
SERVER_MAX_UPLOAD_SIZE = 100 * 1024 * 1024 * 1024  # 100GB maximum upload
SERVER_VALIDATE_FILENAME = True        # Validate filenames for security

# ======================== Directory Initialization ========================
def initialize_directories():
    """Create all necessary directories if they don't exist."""
    directories = [
        MODELS_DIR,
        LOGS_DIR,
        TRANSFER_ROOT,
        INCOMING_DIR,
        COMPLETED_DIR,
        FAILED_DIR,
        QUEUED_DIR
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 DCI Directories initialized:")
    print(f"   Models: {MODELS_DIR}")
    print(f"   Logs: {LOGS_DIR}")
    print(f"   Transfers: {TRANSFER_ROOT}")

# Initialize directories on import
initialize_directories()

# ======================== Configuration Validation ========================
def validate_config():
    """Validate configuration values."""
    errors = []
    
    # Port validation
    if not (1 <= DEFAULT_SERVER_PORT <= 65535):
        errors.append(f"Invalid port: {DEFAULT_SERVER_PORT}. Must be between 1 and 65535.")
    
    # Stream count validation
    if RL_MIN_STREAMS < 1:
        errors.append(f"RL_MIN_STREAMS must be >= 1, got {RL_MIN_STREAMS}")
    if RL_MAX_STREAMS < RL_MIN_STREAMS:
        errors.append(f"RL_MAX_STREAMS ({RL_MAX_STREAMS}) must be >= RL_MIN_STREAMS ({RL_MIN_STREAMS})")
    
    # RL algorithm validation
    if RL_ALGORITHM not in ['qlearning', 'ppo']:
        errors.append(f"Invalid RL_ALGORITHM: {RL_ALGORITHM}. Must be 'qlearning' or 'ppo'.")
    
    # PPO parameter validation
    if RL_ALGORITHM == 'ppo':
        if PPO_STATE_HISTORY_SIZE < 1:
            errors.append(f"PPO_STATE_HISTORY_SIZE must be >= 1, got {PPO_STATE_HISTORY_SIZE}")
        if PPO_LEARNING_RATE <= 0:
            errors.append(f"PPO_LEARNING_RATE must be > 0, got {PPO_LEARNING_RATE}")
        if not (0 <= PPO_GAMMA <= 1):
            errors.append(f"PPO_GAMMA must be between 0 and 1, got {PPO_GAMMA}")
    
    # Utility function parameter validation
    if UTILITY_K <= 1.0:
        errors.append(f"UTILITY_K must be > 1.0, got {UTILITY_K}")
    if UTILITY_B < 0:
        errors.append(f"UTILITY_B must be >= 0, got {UTILITY_B}")
    if UTILITY_EPSILON < 0:
        errors.append(f"UTILITY_EPSILON must be >= 0, got {UTILITY_EPSILON}")
    
    # File size validation
    if MAX_FILE_SIZE <= 0:
        errors.append(f"MAX_FILE_SIZE must be > 0, got {MAX_FILE_SIZE}")
    
    if errors:
        error_msg = "DCI Configuration errors:\n" + "\n".join(errors)
        raise ValueError(error_msg)
    
    return True

# Validate configuration on import
try:
    validate_config()
    print(f"✅ DCI Configuration validated successfully")
    print(f"🤖 RL Algorithm: {RL_ALGORITHM.upper()}")
except ValueError as e:
    print(f"❌ DCI Configuration error: {e}")
    raise

# ======================== Helper Functions ========================
def get_model_path():
    """Get the model directory path as string."""
    return str(MODELS_DIR)

def get_transfer_paths():
    """Get all transfer-related paths."""
    return {
        'incoming': str(INCOMING_DIR),
        'completed': str(COMPLETED_DIR),
        'failed': str(FAILED_DIR),
        'queued': str(QUEUED_DIR),
        'root': str(TRANSFER_ROOT)
    }

def get_algorithm_config():
    """Get configuration for the selected algorithm."""
    if RL_ALGORITHM == 'qlearning':
        return {
            'type': 'qlearning',
            'learning_rate': QL_LEARNING_RATE,
            'discount_factor': QL_DISCOUNT_FACTOR,
            'exploration_rate': QL_EXPLORATION_RATE,
            'min_exploration': QL_MIN_EXPLORATION,
            'exploration_decay': QL_EXPLORATION_DECAY,
            'monitoring_interval': RL_MONITORING_INTERVAL,
            'action_map': QL_ACTION_MAP,
            'state_levels': {
                'throughput': THROUGHPUT_LEVELS,
                'rtt': RTT_LEVELS,
                'loss': LOSS_LEVELS
            }
        }
    else:  # PPO
        return {
            'type': 'ppo',
            'learning_rate': PPO_LEARNING_RATE,
            'gamma': PPO_GAMMA,
            'clip_epsilon': PPO_CLIP_EPSILON,
            'ppo_epochs': PPO_EPOCHS,
            'batch_size': PPO_BATCH_SIZE,
            'hidden_dim': PPO_HIDDEN_DIM,
            'state_history_size': PPO_STATE_HISTORY_SIZE,
            'action_map': PPO_ACTION_MAP,
            'utility_params': {
                'K': UTILITY_K,
                'B': UTILITY_B,
                'epsilon': UTILITY_EPSILON
            }
        }

def get_log_config():
    """Get logging configuration."""
    return {
        'level': LOG_LEVEL,
        'format': LOG_FORMAT,
        'date_format': LOG_DATE_FORMAT,
        'file': LOG_FILE,
        'max_size': LOG_MAX_SIZE,
        'backup_count': LOG_BACKUP_COUNT
    }

def print_config_summary():
    """Print configuration summary."""
    print("=" * 60)
    print("DCI File Sharing System Configuration")
    print("=" * 60)
    print(f"Server: {DEFAULT_SERVER_HOST}:{DEFAULT_SERVER_PORT}")
    print(f"RL Algorithm: {RL_ALGORITHM.upper()}")
    print(f"RL Enabled: {RL_ENABLED}")
    print(f"Streams: {RL_MIN_STREAMS}-{RL_MAX_STREAMS} (Initial: {RL_INITIAL_STREAMS})")
    print(f"Chunk Size: {CHUNK_SIZE/(1024*1024):.1f}MB")
    print(f"Transfer Root: {TRANSFER_ROOT}")
    print(f"Log File: {LOG_FILE}")
    print("=" * 60)

# Print configuration summary on import
print_config_summary()