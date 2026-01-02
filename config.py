"""
config.py - Configuration for RL-based Multi-Stream Downloader
Updated for PyTorch PPO implementation with comprehensive parameters.
"""
import os

# ======================== Download Settings ========================
DEFAULT_NUM_STREAMS = 8
MIN_STREAMS = 1
MAX_STREAMS = 32  # Increased for more flexibility with RL

# Chunk settings
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024   # 4 MB default chunk size
MIN_CHUNK_SIZE = 1024 * 1024           # 1 MB minimum
BUFFER_SIZE = 8192                     # 8 KB buffer for streaming

# Network settings
CONNECTION_TIMEOUT = 10                # Connection timeout in seconds
READ_TIMEOUT = 30                      # Read timeout in seconds
MAX_RETRIES = 3                        # Maximum retry attempts per chunk
RETRY_DELAY = 2                        # Delay between retries in seconds

# ======================== RL Core Settings ========================
# Monitoring Interval (MI) - Section 3 of paper
RL_MONITORING_INTERVAL = 3.0           # seconds between RL decisions (reduced for faster learning)

# Episode settings
MAX_EPISODE_STEPS = 1000               # Maximum steps per episode
MIN_EPISODE_STEPS = 10                 # Minimum steps before episode can end

# ======================== PPO Hyperparameters ========================
# Based on stable-baselines3 defaults and paper recommendations
PPO_LEARNING_RATE = 3e-4              # Standard learning rate for PPO
PPO_GAMMA = 0.99                      # Discount factor for future rewards
PPO_CLIP_PARAM = 0.2                  # PPO clipping parameter (epsilon)
PPO_ENTROPY_COEF = 0.01               # Entropy coefficient for exploration
PPO_VALUE_COEF = 0.5                  # Value function coefficient
PPO_MAX_GRAD_NORM = 0.5               # Gradient clipping norm
PPO_EPOCHS = 10                       # Number of PPO epochs per update
PPO_BATCH_SIZE = 64                   # Minibatch size for training
PPO_GAE_LAMBDA = 0.95                 # GAE lambda parameter

# Network architecture
PPO_HIDDEN_SIZE = 256                 # Hidden layer size in neural network
PPO_HISTORY_LENGTH = 4                # Number of past steps in state
PPO_STATE_DIM = 4 * PPO_HISTORY_LENGTH  # State dimension: 4 metrics × 4 timesteps

# ======================== Exploration Parameters ========================
INITIAL_EXPLORATION = 1.0             # Initial exploration rate (100% random)
FINAL_EXPLORATION = 0.05              # Final exploration rate (5% random)
EXPLORATION_DECAY_STEPS = 2000        # Steps over which to decay exploration

# ======================== Utility Function Parameters ========================
# CRITICAL: These parameters define the reward function (Paper Equation 3)
# U(n_i, T_i, L_i) = (T_i / K^n_i) - (T_i * L_i * B)

# Based on your network characteristics (~35 Mbps peak, ~1.5% typical loss)
UTILITY_K = 1.01                      # Diminishing returns factor
                                        # K=1.01 means: each additional stream reduces 
                                        # performance by ~1% of throughput
                                        # Lower = stronger penalty for many streams
                                        # Higher = weaker penalty
                                        # Optimal range: 1.01-1.02 for your network

UTILITY_B = 25.0                      # Packet loss punishment coefficient
                                        # B=25.0 means: 1% packet loss reduces utility
                                        # by 25% of throughput
                                        # Lower = agent tolerates more congestion
                                        # Higher = agent avoids congestion aggressively
                                        # Optimal range: 20-30 for your network

UTILITY_EPSILON = 0.5                 # Reward threshold (absolute utility units)
                                        # If utility change > epsilon: positive reward
                                        # If utility change < -epsilon: negative reward
                                        # Otherwise: neutral (0 reward)
                                        # With utility ~25-30, epsilon=0.5 is ~2% threshold

# ======================== Reward Values ========================
REWARD_POSITIVE = 1.0                 # Base reward for improving performance
REWARD_NEGATIVE = -1.0                # Base penalty for degrading performance
REWARD_NEUTRAL = 0.0                  # No significant change

# Episode completion rewards
REWARD_EPISODE_SUCCESS = 10.0         # Reward for successful episode completion
REWARD_EPISODE_FAILURE = -5.0         # Penalty for failed episode
REWARD_EFFICIENCY_BONUS = 2.0         # Bonus for efficient stream usage
REWARD_SPEED_BONUS_MAX = 5.0          # Maximum bonus for fast download

# ======================== Buffer and Training Settings ========================
MIN_BUFFER_SIZE = 32                  # Minimum experiences before training
TARGET_BUFFER_SIZE = 128              # Target buffer size for training
MAX_BUFFER_SIZE = 1024                # Maximum buffer size (for memory management)

TRAINING_FREQUENCY = 1                # Train every N monitoring intervals
SAVE_FREQUENCY = 10                   # Save model every N training updates

# ======================== Network State Discretization ========================
# (For reference - not used by PPO which uses continuous states)
THROUGHPUT_LEVELS = 5                 # Very Low, Low, Medium, High, Very High
RTT_LEVELS = 4                        # Excellent, Good, Fair, Poor
LOSS_LEVELS = 4                       # Excellent, Good, Fair, Poor

# Throughput thresholds (Mbps)
THROUGHPUT_THRESHOLDS = [5, 15, 25, 35]

# RTT thresholds (ms)
RTT_THRESHOLDS = [50, 100, 200]

# Packet loss thresholds (%)
LOSS_THRESHOLDS = [0.5, 1.5, 3.0]

# ======================== Application Settings ========================
DOWNLOAD_FOLDER = os.path.join(
    os.path.expanduser("~"), 
    "Downloads", 
    "MultiStreamDownloader"
)

# Flask web interface
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 5000
FLASK_DEBUG = True

# Model persistence
Q_TABLE_FILE = 'q_table.json'           # Base filename (PPO uses q_table_ppo.pt)
Q_TABLE_BACKUP = 'q_table_backup.json'
MODEL_AUTO_SAVE = True                 # Auto-save model after training
MODEL_BACKUP_COUNT = 5                 # Number of backup models to keep

# Performance monitoring
HEALTH_CHECK_INTERVAL = 10
PROGRESS_CHECK_INTERVAL = 5
NO_PROGRESS_TIMEOUT = 30               # Timeout if no progress (seconds)
MAX_DOWNLOAD_TIME = 3600               # Maximum total download time (1 hour)

# Create download folder
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# ======================== Logging Configuration ========================
ENABLE_VERBOSE_LOGGING = True          # Enable detailed logging
LOG_TO_FILE = True                     # Log to file in addition to console
LOG_FILE = 'downloader.log'            # Log file name
LOG_LEVEL = 'INFO'                     # DEBUG, INFO, WARNING, ERROR

# RL-specific logging
LOG_RL_DECISIONS = True                # Log each RL decision with metrics
LOG_NETWORK_METRICS = True             # Log throughput, RTT, packet loss updates
LOG_PPO_TRAINING = True                # Log PPO training updates
LOG_UTILITY_CALCULATIONS = False       # Detailed utility function logging (verbose)
LOG_ACTION_DISTRIBUTION = True         # Log action probability distribution
LOG_EPISODE_SUMMARY = True             # Log episode completion summary

# Network metrics logging frequency
NETWORK_METRICS_LOG_INTERVAL = 5       # Log metrics every N steps

# ======================== Testing and Debugging ========================
ENABLE_TEST_MODE = False               # Enable test mode (simulated downloads)
SIMULATED_THROUGHPUT = 35.0            # Simulated throughput in Mbps
SIMULATED_RTT = 100.0                  # Simulated RTT in ms
SIMULATED_LOSS = 1.5                   # Simulated packet loss in %

# Diagnostic tools
ENABLE_DIAGNOSTICS = True              # Enable periodic diagnostic checks
DIAGNOSTIC_INTERVAL = 100              # Run diagnostics every N decisions

# ======================== Performance Optimization ========================
ENABLE_PREFETCH = True                 # Enable chunk prefetching
PREFETCH_FACTOR = 1.5                  # Prefetch N times current stream count
MAX_CONCURRENT_DNS = 10                # Maximum concurrent DNS lookups
ENABLE_CONNECTION_POOLING = True       # Enable HTTP connection pooling
CONNECTION_POOL_SIZE = 20              # Size of connection pool

# ======================== Security Settings ========================
MAX_URL_LENGTH = 2048                  # Maximum URL length
ALLOWED_SCHEMES = ['http', 'https']    # Allowed URL schemes
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # Maximum file size (10 GB)
MAX_CHUNKS = 1000                      # Maximum number of chunks

# SSL verification
VERIFY_SSL = True                      # Verify SSL certificates
SSL_TIMEOUT = 10                       # SSL handshake timeout

# ======================== User Interface Settings ========================
UPDATE_INTERVAL_MS = 1000              # UI update interval in milliseconds
MAX_HISTORY_POINTS = 100               # Maximum points in history charts
ENABLE_REALTIME_GRAPHS = True          # Enable real-time performance graphs

# ======================== Documentation Strings ========================
"""
PPO IMPLEMENTATION NOTES:
========================

1. PAPER REFERENCE:
   "A Reinforcement Learning Approach to Optimize Available Network Bandwidth Utilization"
   - Jamil et al., University at Buffalo (SUNY)
   
   Key sections implemented:
   - Section 3.1.1: State representation (RTT gradient, RTT ratio, PLR, throughput)
   - Section 3.1.2: Action space (5 actions: ±5, ±1, 0)
   - Section 3.1.3: Utility function (Equation 3)
   - Algorithm 1: PPO training procedure

2. STATE REPRESENTATION:
   State vector includes last 4 time steps of:
   - RTT gradient (normalized)
   - RTT ratio (current/min observed)
   - Packet loss rate (normalized 0-0.1)
   - Throughput (normalized 0-1 based on 100 Mbps)
   
   Total state dimension: 4 metrics × 4 timesteps = 16

3. ACTION SPACE:
   0: Aggressive Increase (+5 streams)
   1: Conservative Increase (+1 stream)
   2: No Change (0)
   3: Conservative Decrease (-1 stream)
   4: Aggressive Decrease (-5 streams)

4. UTILITY FUNCTION EXPLANATION:
   U(n, T, L) = (T / K^n) - (T * L * B)
   
   Where:
   - n: Number of parallel TCP streams
   - T: Throughput in Mbps
   - L: Packet loss rate (decimal, e.g., 0.015 for 1.5%)
   - K: Diminishing returns factor (K^n grows with n)
   - B: Packet loss punishment coefficient
   
   Examples for your network (35 Mbps, 1.5% loss):
   - 1 stream:  U = 35/1.01^1 - 35*0.015*25 = 34.65 - 13.13 = 21.52
   - 5 streams: U = 35/1.01^5 - 35*0.015*25 = 33.30 - 13.13 = 20.17
   - 10 streams: U = 35/1.01^10 - 35*0.015*25 = 31.68 - 13.13 = 18.55
   - 15 streams: U = 35/1.01^15 - 35*0.015*25 = 30.14 - 13.13 = 17.01
   
   Optimal range: 6-10 streams (utility ~18-20)

5. REWARD FUNCTION:
   Reward = sign(ΔU) × (1 + min(|ΔU|/10, 2))
   Where ΔU = current utility - previous utility
   
   Positive reward for ΔU > UTILITY_EPSILON
   Negative reward for ΔU < -UTILITY_EPSILON
   Zero reward otherwise

6. PPO TRAINING SCHEDULE:
   - Collect experience until buffer has 128 steps
   - Train for 10 epochs with minibatches of 64
   - Update network using clipped surrogate objective
   - Save model every 10 training updates
   - Decay exploration from 1.0 to 0.05 over 2000 steps

7. EXPECTED PERFORMANCE:
   Phase 1 (Decisions 1-50):  Heavy exploration, stream count varies widely
   Phase 2 (Decisions 50-200): Learning, converging to optimal range (6-10 streams)
   Phase 3 (Decisions 200+):  Stable, maintaining optimal streams with adaptation
   
   Throughput should stabilize around 32-35 Mbps (not drop below 30 Mbps)

8. TROUBLESHOOTING:
   
   Q: Agent converges to 1-3 streams only
   A: Increase UTILITY_K to 1.02 or decrease UTILITY_B to 20.0
   
   Q: Agent uses too many streams (>15)
   A: Decrease UTILITY_K to 1.005 or increase UTILITY_B to 30.0
   
   Q: No learning (rewards don't improve)
   A: Check LOG_PPO_TRAINING=True, ensure buffer fills and training occurs
   
   Q: Throughput drops significantly
   A: Run diagnostics, check utility function parameters match your network
   
   Q: Model not saving/loading
   A: Check file permissions, ensure PyTorch is installed correctly

9. VERIFICATION CHECKLIST:
   ✓ config.py has UTILITY_K=1.01, UTILITY_B=25.0
   ✓ rl_manager.py imports from config (not hardcoded)
   ✓ PyTorch installed: pip install torch
   ✓ Download folder exists and writable
   ✓ Logging enabled to monitor behavior
   ✓ Network supports range requests (for multi-stream)

10. OPTIMIZATION TIPS:
    - Adjust RL_MONITORING_INTERVAL based on network stability
    - Tune UTILITY_K/B for your specific network conditions
    - Increase PPO_HIDDEN_SIZE for complex networks
    - Adjust exploration decay based on learning speed
    - Monitor logs to verify learning is occurring
"""

# ======================== Environment Validation ========================
def validate_config():
    """Validate configuration settings."""
    errors = []
    
    # Check folder permissions
    if not os.access(DOWNLOAD_FOLDER, os.W_OK):
        errors.append(f"Download folder not writable: {DOWNLOAD_FOLDER}")
    
    # Check parameter ranges
    if UTILITY_K <= 1.0:
        errors.append(f"UTILITY_K must be > 1.0, got {UTILITY_K}")
    
    if UTILITY_B <= 0:
        errors.append(f"UTILITY_B must be > 0, got {UTILITY_B}")
    
    if RL_MONITORING_INTERVAL < 1.0:
        errors.append(f"RL_MONITORING_INTERVAL too small: {RL_MONITORING_INTERVAL}")
    
    if MAX_STREAMS < MIN_STREAMS:
        errors.append(f"MAX_STREAMS ({MAX_STREAMS}) < MIN_STREAMS ({MIN_STREAMS})")
    
    return errors

# Validate on import
config_errors = validate_config()
if config_errors:
    print("⚠️  Configuration errors detected:")
    for error in config_errors:
        print(f"   - {error}")
    print("Some features may not work correctly.")
else:
    print("✅ Configuration validated successfully")

# ======================== Version Information ========================
CONFIG_VERSION = "2.0.0"
CONFIG_DATE = "2024-01-20"
CONFIG_DESCRIPTION = "PPO-based Multi-Stream Downloader Configuration"

print(f"\n📋 {CONFIG_DESCRIPTION}")
print(f"   Version: {CONFIG_VERSION} | Date: {CONFIG_DATE}")
print(f"   Download folder: {DOWNLOAD_FOLDER}")
print(f"   Max streams: {MAX_STREAMS} | Monitoring interval: {RL_MONITORING_INTERVAL}s")
print(f"   Utility params: K={UTILITY_K}, B={UTILITY_B}, ε={UTILITY_EPSILON}")
print(f"   PPO params: LR={PPO_LEARNING_RATE}, Clip={PPO_CLIP_PARAM}, Epochs={PPO_EPOCHS}")
print("="*70)