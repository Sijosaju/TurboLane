"""
config.py - Optimized Configuration with Safety Constraints
"""

import os
import numpy as np

# ======================== Download Settings ========================
DEFAULT_NUM_STREAMS = 6  # Start in optimal range
MIN_STREAMS = 2  # INCREASED from 1 - at least 2 streams
MAX_STREAMS = 20  # REDUCED from 50 - paper shows optimal is typically 6-12

# Safety bounds - hard limits
ABSOLUTE_MAX_STREAMS = 25  # Never exceed this
SAFE_MAX_STREAMS = 15  # Preferred maximum
OPTIMAL_MIN_STREAMS = 4  # Don't go below this in good conditions
OPTIMAL_MAX_STREAMS = 12  # Sweet spot upper bound

# Chunk settings
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB
MIN_CHUNK_SIZE = 1024 * 1024  # 1 MB
BUFFER_SIZE = 8192

# Network settings
CONNECTION_TIMEOUT = 10
READ_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2

# ======================== RL Settings (Paper-Based with Safety) ========================

# Monitoring Interval
RL_MONITORING_INTERVAL = 5.0  # seconds

# Q-Learning parameters (More conservative for safety)
RL_LEARNING_RATE = 0.0001
RL_DISCOUNT_FACTOR = 1.0
RL_EXPLORATION_RATE = 0.7  # REDUCED from 0.9 - less aggressive exploration
RL_MIN_EXPLORATION = 0.05
RL_EXPLORATION_DECAY = 0.996  # Faster decay to reduce wild exploration

# Utility function parameters
UTILITY_K = 0.02  # INCREASED from 0.01 - higher cost per stream (discourages too many)
UTILITY_B = 2000  # INCREASED from 1000 - stronger packet loss punishment
UTILITY_EPSILON = 0.01

# Reward values
REWARD_POSITIVE = 10.0
REWARD_NEGATIVE = -15.0  # INCREASED penalty to discourage bad actions faster
REWARD_NEUTRAL = 0.0

# Throughput bonus parameters (Adjusted for safety)
THROUGHPUT_BONUS_SCALE = 3.0  # REDUCED from 5.0
IMPROVEMENT_BONUS_SCALE = 2.0  # REDUCED from 3.0
LOSS_PENALTY_MULTIPLIER = 100.0  # INCREASED from 50.0 - severe congestion penalty

# Congestion detection thresholds
CONGESTION_LOSS_THRESHOLD = 1.0  # % - packet loss indicating congestion
SEVERE_CONGESTION_THRESHOLD = 3.0  # % - severe congestion
HIGH_RTT_THRESHOLD = 200  # ms - indicates network stress

# State discretization
STATE_HISTORY_LENGTH = 3

# Throughput bins (Mbps)
THROUGHPUT_BINS = [0, 10, 20, 30, 50, 75, 100]

# RTT gradient bins
RTT_GRADIENT_BINS = [-0.5, -0.1, 0, 0.1, 0.5]

# Packet loss bins (%) - More granular for better congestion detection
PACKET_LOSS_BINS = [0, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0]

# ======================== Action Space (Conservative) ========================
# CHANGED: Smaller increments to prevent overshooting
ACTION_SPACE = {
    0: 3,   # Moderate increase (+3 instead of +5)
    1: 1,   # Conservative increase (+1)
    2: 0,   # No change
    3: -1,  # Conservative decrease (-1)
    4: -3   # Moderate decrease (-3 instead of -5)
}

# Safety: Emergency action when congestion detected
EMERGENCY_DECREASE = -5  # Rapid decrease in emergency

# ======================== Application Settings ========================
DOWNLOAD_FOLDER = os.path.join(
    os.path.expanduser("~"),
    "Downloads",
    "MultiStreamDownloader"
)

# Flask web interface
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 5000
FLASK_DEBUG = False

# Q-table persistence
Q_TABLE_FILE = 'q_table_safe.json'
Q_TABLE_BACKUP = 'q_table_safe_backup.json'
Q_TABLE_SAVE_INTERVAL = 50  # Save more frequently

# Performance monitoring
HEALTH_CHECK_INTERVAL = 10
PROGRESS_CHECK_INTERVAL = 10
NO_PROGRESS_TIMEOUT = 30

# Create download folder
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# ======================== Logging ========================
ENABLE_VERBOSE_LOGGING = True
LOG_RL_DECISIONS = True
LOG_NETWORK_METRICS = True
LOG_Q_TABLE_UPDATES = False  # Too verbose
LOG_REWARD_DETAILS = True
LOG_SAFETY_INTERVENTIONS = True  # NEW: Log when safety kicks in

print("âœ… Configuration loaded - SAFE MODE with congestion prevention")
print(f"   Stream bounds: {MIN_STREAMS}-{MAX_STREAMS} (optimal: {OPTIMAL_MIN_STREAMS}-{OPTIMAL_MAX_STREAMS})")
print(f"   Safety: K={UTILITY_K}, B={UTILITY_B}")