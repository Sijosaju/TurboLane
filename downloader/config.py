"""
downloader/config.py - Configuration for RL-based Multi-Stream Downloader
Updated with PPO algorithm support and paper's exact parameters.
OPTIMIZED VERSION - Fixed batch size for proper PPO updates.
"""
import os
from pathlib import Path

# ======================== Project Structure ========================
PROJECT_ROOT = Path(__file__).parent.parent
MODELS_DIR = PROJECT_ROOT / "models"
LOGS_DIR = PROJECT_ROOT / "logs"

# ======================== Download Settings ========================
DEFAULT_NUM_STREAMS = 8
MIN_STREAMS = 1
MAX_STREAMS = 16

# Chunk settings
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024   # 4 MB default chunk size
MIN_CHUNK_SIZE = 1024 * 1024           # 1 MB minimum
MAX_CHUNK_SIZE = 10 * 1024 * 1024      # 10 MB maximum
BUFFER_SIZE = 8192                     # 8KB buffer for streaming

# Network settings
CONNECTION_TIMEOUT = 10                # Connection timeout in seconds
READ_TIMEOUT = 30                      # Read timeout in seconds
MAX_RETRIES = 3                        # Maximum retry attempts
RETRY_DELAY = 2                        # Delay between retries in seconds
MAX_REDIRECTS = 5                      # Maximum HTTP redirects

# ======================== RL Algorithm Selection ========================
# Choose between "qlearning" (legacy) or "ppo" (paper's algorithm)
RL_ALGORITHM = "ppo"  # Options: "qlearning" or "ppo"

# ======================== PPO Specific Settings (Paper's Algorithm) ========================
PPO_STATE_HISTORY_SIZE = 5             # n from paper (bounded history of states)
PPO_LEARNING_RATE = 0.0003             # Adam optimizer learning rate (reduced for stability)
PPO_GAMMA = 0.99                       # Discount factor for future rewards
PPO_CLIP_EPSILON = 0.2                 # PPO clipping parameter
PPO_EPOCHS = 4                         # Number of PPO update epochs (reduced from 10)
PPO_BATCH_SIZE = 20                    # ✅ FIXED: Batch size for training (was 64, now 20)
PPO_HIDDEN_DIM = 64                    # Neural network hidden dimension
PPO_ENTROPY_COEFF = 0.01               # Entropy coefficient for exploration
PPO_VALUE_COEFF = 0.5                  # Value loss coefficient
PPO_MAX_GRAD_NORM = 0.5                # Gradient clipping
PPO_GAE_LAMBDA = 0.95                  # GAE lambda parameter
PPO_EXPLORATION_STEPS = 100            # Steps to decay exploration rate

# Paper's utility function parameters (Equation 3)
UTILITY_K = 1.02                       # Cost per stream (K)
UTILITY_B = 5.0                        # Punishment coefficient (B)
UTILITY_EPSILON = 0.08                 # 8% relative threshold (ε)

# Action mapping for PPO (more conservative than paper)
# Paper used: [-5, -1, 0, +1, +5]
# We use: [-2, -1, 0, +1, +2] for more stable adjustments
PPO_ACTION_MAP = [-2, -1, 0, +1, +2]

# ======================== Q-Learning Settings (Legacy - for backward compatibility) ========================
RL_MONITORING_INTERVAL = 5.0           # seconds between RL decisions (Monitoring Intervals)
RL_LEARNING_RATE = 0.1                 # α - learning rate
RL_DISCOUNT_FACTOR = 0.8               # γ - discount factor
RL_EXPLORATION_RATE = 0.3              # ε - initial exploration rate
RL_MIN_EXPLORATION = 0.05              # minimum exploration rate
RL_EXPLORATION_DECAY = 0.995           # exploration decay rate

# Q-learning action mapping (legacy: -2, -1, 0, +1, +2)
QL_ACTION_MAP = [-2, -1, 0, +1, +2]

# State discretization levels (for Q-learning only)
THROUGHPUT_LEVELS = 6                  # Very Low, Low, Medium, High, Very High, Excellent
RTT_LEVELS = 4                         # Excellent, Good, Poor, Very Poor
LOSS_LEVELS = 5                        # Excellent, Good, Moderate, Poor, Very Poor

# Reward values (for Q-learning only)
REWARD_POSITIVE = 1.0
REWARD_NEGATIVE = -1.0
REWARD_NEUTRAL = 0.0

# ======================== Application Settings ========================
DOWNLOAD_FOLDER = os.path.join(
    os.path.expanduser("~"), 
    "Downloads", 
    "MultiStreamDownloader"
)

# Default download folder structure
TEMP_FOLDER = os.path.join(DOWNLOAD_FOLDER, "temp")
COMPLETED_FOLDER = os.path.join(DOWNLOAD_FOLDER, "completed")
FAILED_FOLDER = os.path.join(DOWNLOAD_FOLDER, "failed")

# Flask web interface
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 5000
FLASK_DEBUG = False
FLASK_THREADED = True
FLASK_MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload

# Model persistence paths
Q_TABLE_PATH = str(MODELS_DIR / "qlearning")
PPO_MODEL_PATH = str(MODELS_DIR / "ppo")
Q_TABLE_FILE = 'q_table.json'
Q_TABLE_BACKUP = 'q_table_backup.json'
PPO_MODEL_FILE = 'ppo_model.pt'
PPO_METADATA_FILE = 'ppo_metadata.json'
MODEL_SAVE_INTERVAL = 50  # Save every N decisions

# Performance monitoring
HEALTH_CHECK_INTERVAL = 10
PROGRESS_CHECK_INTERVAL = 10
NO_PROGRESS_TIMEOUT = 30
STALLED_TIMEOUT = 60

# Chunk management
MAX_CONCURRENT_CHUNKS = 32
CHUNK_RETRY_LIMIT = 3
CHUNK_TIMEOUT = 300  # 5 minutes per chunk

# File assembly
ASSEMBLY_BUFFER_SIZE = 16 * 1024 * 1024  # 16MB buffer for file assembly
VERIFY_FILE_SIZE = True
CLEANUP_TEMP_FILES = True

# ======================== Logging Configuration ========================
ENABLE_VERBOSE_LOGGING = True
LOG_RL_DECISIONS = True
LOG_NETWORK_METRICS = True
LOG_Q_TABLE_UPDATES = False
LOG_PPO_UPDATES = True
LOG_CHUNK_EVENTS = False

# Log levels
LOG_LEVEL = "INFO"
LOG_FILE = str(LOGS_DIR / "downloader.log")
LOG_MAX_SIZE = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5

# Log format
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# ======================== Advanced RL Settings ========================
# State normalization parameters
STATE_NORMALIZATION = {
    'throughput_max': 1000.0,          # Normalize throughput by 1000 Mbps
    'rtt_max': 500.0,                  # Normalize RTT by 500 ms
    'loss_max': 5.0,                   # Normalize packet loss by 5%
    'rtt_gradient_max': 100.0,         # Normalize RTT gradient by 100 ms/s
    'rtt_ratio_max': 10.0              # Maximum RTT ratio
}

# Exploration strategy
EXPLORATION_STRATEGY = "epsilon_greedy"  # Options: "epsilon_greedy", "boltzmann", "ucb"
INITIAL_TEMPERATURE = 1.0              # For Boltzmann exploration
TEMPERATURE_DECAY = 0.995

# ======================== Safety Limits ========================
MAX_DOWNLOAD_SIZE = 10 * 1024 * 1024 * 1024  # 10GB maximum download
MAX_CHUNKS_PER_FILE = 1000
MIN_BYTES_FOR_RL = 10 * 1024 * 1024    # 10MB minimum for RL optimization
MAX_CONNECTIONS_PER_HOST = 100

# Rate limiting
MAX_REQUESTS_PER_MINUTE = 60
RATE_LIMIT_WINDOW = 60

# Security settings
ALLOWED_DOMAINS = []                    # Empty list means all domains allowed
BLOCKED_DOMAINS = []
VALIDATE_SSL_CERTIFICATES = True
USER_AGENT = "TurboLane-Downloader/1.0"

# ======================== Statistics and Reporting ========================
COLLECT_STATISTICS = True
STATISTICS_INTERVAL = 60                # Collect stats every 60 seconds
SAVE_STATISTICS = True
STATISTICS_FILE = str(LOGS_DIR / "statistics.json")

# Performance metrics to track
TRACK_METRICS = [
    'throughput',
    'rtt',
    'packet_loss',
    'utility',
    'reward',
    'stream_count',
    'chunk_success_rate',
    'download_time',
    'file_size'
]

# ======================== Create Required Directories ========================
def initialize_directories():
    """Create all necessary directories if they don't exist."""
    directories = [
        DOWNLOAD_FOLDER,
        TEMP_FOLDER,
        COMPLETED_FOLDER,
        FAILED_FOLDER,
        MODELS_DIR,
        LOGS_DIR,
        Q_TABLE_PATH,
        PPO_MODEL_PATH
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
    
    print(f"📁 Initialized directories:")
    print(f"   Downloads: {DOWNLOAD_FOLDER}")
    print(f"   Models: {MODELS_DIR}")
    print(f"   Logs: {LOGS_DIR}")

# Initialize directories on import
initialize_directories()

# ======================== Configuration Validation ========================
def validate_config():
    """Validate configuration values."""
    errors = []
    warnings = []
    
    # RL algorithm validation
    if RL_ALGORITHM not in ['qlearning', 'ppo']:
        errors.append(f"Invalid RL_ALGORITHM: {RL_ALGORITHM}. Must be 'qlearning' or 'ppo'.")
    
    # Stream count validation
    if MIN_STREAMS < 1:
        errors.append(f"MIN_STREAMS must be >= 1, got {MIN_STREAMS}")
    if MAX_STREAMS < MIN_STREAMS:
        errors.append(f"MAX_STREAMS ({MAX_STREAMS}) must be >= MIN_STREAMS ({MIN_STREAMS})")
    
    # PPO parameter validation
    if RL_ALGORITHM == 'ppo':
        if PPO_STATE_HISTORY_SIZE < 1:
            errors.append(f"PPO_STATE_HISTORY_SIZE must be >= 1, got {PPO_STATE_HISTORY_SIZE}")
        if PPO_LEARNING_RATE <= 0:
            errors.append(f"PPO_LEARNING_RATE must be > 0, got {PPO_LEARNING_RATE}")
        if not (0 <= PPO_GAMMA <= 1):
            errors.append(f"PPO_GAMMA must be between 0 and 1, got {PPO_GAMMA}")
        if PPO_CLIP_EPSILON <= 0:
            errors.append(f"PPO_CLIP_EPSILON must be > 0, got {PPO_CLIP_EPSILON}")
        
        # Batch size warnings
        if PPO_BATCH_SIZE > 50:
            warnings.append(f"⚠️ PPO_BATCH_SIZE is quite large ({PPO_BATCH_SIZE}). "
                          f"Consider 20-30 for faster updates during short downloads.")
        if PPO_BATCH_SIZE < 10:
            warnings.append(f"⚠️ PPO_BATCH_SIZE is very small ({PPO_BATCH_SIZE}). "
                          f"May lead to unstable learning.")
    
    # Utility function parameter validation
    if UTILITY_K <= 1.0:
        errors.append(f"UTILITY_K must be > 1.0, got {UTILITY_K}")
    if UTILITY_B < 0:
        errors.append(f"UTILITY_B must be >= 0, got {UTILITY_B}")
    if UTILITY_EPSILON < 0:
        errors.append(f"UTILITY_EPSILON must be >= 0, got {UTILITY_EPSILON}")
    
    if errors:
        error_msg = "❌ Configuration errors:\n" + "\n".join(errors)
        raise ValueError(error_msg)
    
    if warnings:
        print("\n⚠️ Configuration warnings:")
        for warning in warnings:
            print(f"   {warning}")
        print()
    
    return True

# Validate configuration on import
try:
    validate_config()
    print(f"✅ Configuration validated successfully")
    print(f"🤖 RL Algorithm: {RL_ALGORITHM.upper()}")
    if RL_ALGORITHM == 'ppo':
        print(f"   Batch Size: {PPO_BATCH_SIZE} (updates every ~{PPO_BATCH_SIZE} decisions)")
        print(f"   Learning Rate: {PPO_LEARNING_RATE}")
        print(f"   Action Space: {PPO_ACTION_MAP}")
except ValueError as e:
    print(f"❌ Configuration error: {e}")
    raise

# ======================== Helper Functions ========================
def get_algorithm_config():
    """Get configuration for the selected algorithm."""
    if RL_ALGORITHM == 'qlearning':
        return {
            'type': 'qlearning',
            'learning_rate': RL_LEARNING_RATE,
            'discount_factor': RL_DISCOUNT_FACTOR,
            'exploration_rate': RL_EXPLORATION_RATE,
            'min_exploration': RL_MIN_EXPLORATION,
            'exploration_decay': RL_EXPLORATION_DECAY,
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
            'gae_lambda': PPO_GAE_LAMBDA,
            'clip_epsilon': PPO_CLIP_EPSILON,
            'ppo_epochs': PPO_EPOCHS,
            'batch_size': PPO_BATCH_SIZE,
            'hidden_dim': PPO_HIDDEN_DIM,
            'state_history_size': PPO_STATE_HISTORY_SIZE,
            'action_map': PPO_ACTION_MAP,
            'entropy_coef': PPO_ENTROPY_COEFF,
            'value_coef': PPO_VALUE_COEFF,
            'max_grad_norm': PPO_MAX_GRAD_NORM,
            'exploration_steps': PPO_EXPLORATION_STEPS,
            'utility_params': {
                'K': UTILITY_K,
                'B': UTILITY_B,
                'epsilon': UTILITY_EPSILON
            }
        }

def get_model_path(algorithm=None):
    """Get the model path for the specified algorithm."""
    if algorithm is None:
        algorithm = RL_ALGORITHM
    
    if algorithm == 'qlearning':
        return Q_TABLE_PATH
    else:  # PPO
        return PPO_MODEL_PATH

def get_model_file(algorithm=None):
    """Get the model filename for the specified algorithm."""
    if algorithm is None:
        algorithm = RL_ALGORITHM
    
    if algorithm == 'qlearning':
        return Q_TABLE_FILE
    else:  # PPO
        return PPO_MODEL_FILE

def get_ppo_config_dict():
    """Get PPO configuration as a dictionary for easy passing to agent."""
    return {
        'state_history_size': PPO_STATE_HISTORY_SIZE,
        'learning_rate': PPO_LEARNING_RATE,
        'gamma': PPO_GAMMA,
        'gae_lambda': PPO_GAE_LAMBDA,
        'clip_epsilon': PPO_CLIP_EPSILON,
        'ppo_epochs': PPO_EPOCHS,
        'batch_size': PPO_BATCH_SIZE,
        'entropy_coef': PPO_ENTROPY_COEFF,
        'value_coef': PPO_VALUE_COEFF,
        'max_grad_norm': PPO_MAX_GRAD_NORM,
        'min_connections': MIN_STREAMS,
        'max_connections': MAX_STREAMS,
        'default_connections': DEFAULT_NUM_STREAMS // 2,  # Start conservative
        'exploration_steps': PPO_EXPLORATION_STEPS
    }

# Print configuration summary
print("=" * 60)
print("TurboLane Downloader Configuration")
print("=" * 60)
print(f"Algorithm: {RL_ALGORITHM.upper()}")
print(f"Min Streams: {MIN_STREAMS}")
print(f"Max Streams: {MAX_STREAMS}")
print(f"Default Streams: {DEFAULT_NUM_STREAMS}")
if RL_ALGORITHM == 'ppo':
    print(f"PPO Batch Size: {PPO_BATCH_SIZE}")
    print(f"PPO Learning Rate: {PPO_LEARNING_RATE}")
print(f"Download Folder: {DOWNLOAD_FOLDER}")
print(f"Web Interface: http://{FLASK_HOST}:{FLASK_PORT}")
print("=" * 60)