"""
turbolane/modes/dci.py - DCI (Data Center Interconnect) Policy
Simpler policy for inter-site transfers where we don't have real-time network metrics.
"""
import json
import os
import time
from turbolane.rl.storage import QTableStorage


class DCIPolicy:
    """
    DCI transfer policy using simplified state representation.
    
    Unlike the client mode which has real-time network metrics (throughput, RTT, packet loss),
    DCI transfers operate in a different context:
    - File size is known upfront
    - Network is typically stable datacenter-to-datacenter link
    - We learn optimal streams based on file size categories
    """
    
    def __init__(self, model_path='models/dci_model'):
        """
        Initialize DCI policy.
        
        Args:
            model_path: Path to DCI-specific model directory
        """
        self.model_path = model_path
        self.storage = QTableStorage(storage_path=model_path)
        
        # Load existing Q-table or initialize
        self.Q, self.metadata = self.storage.load()
        
        # Simple state: just file size category
        # Actions: number of streams (1-16)
        self.min_streams = 1
        self.max_streams = 16
        self.default_streams = 4
        
        # Learning parameters
        self.learning_rate = 0.1
        self.exploration_rate = 0.2
        self.min_exploration = 0.05
        self.exploration_decay = 0.98
        
        # Statistics
        self.total_transfers = self.metadata.get('total_transfers', 0)
        self.total_updates = self.metadata.get('total_updates', 0)
        
        print(f"📊 DCI Policy initialized with model: {model_path}")
        print(f"   States: {len(self.Q)}, Transfers: {self.total_transfers}")
    
    def _get_file_size_state(self, filesize_bytes):
        """
        Convert file size to discrete state.
        
        States:
        - 'tiny': < 10MB
        - 'small': 10MB - 100MB
        - 'medium': 100MB - 1GB
        - 'large': 1GB - 10GB
        - 'xlarge': 10GB - 100GB
        - 'huge': > 100GB
        """
        MB = 1024 * 1024
        GB = 1024 * MB
        
        if filesize_bytes < 10 * MB:
            return 'tiny'
        elif filesize_bytes < 100 * MB:
            return 'small'
        elif filesize_bytes < 1 * GB:
            return 'medium'
        elif filesize_bytes < 10 * GB:
            return 'large'
        elif filesize_bytes < 100 * GB:
            return 'xlarge'
        else:
            return 'huge'
    
    def get_optimal_streams(self, filesize_bytes):
        """
        Get optimal number of streams for a file transfer.
        
        Args:
            filesize_bytes: File size in bytes
        
        Returns:
            int: Optimal number of streams (1-16)
        """
        state = self._get_file_size_state(filesize_bytes)
        
        # Initialize state if new
        if state not in self.Q:
            self.Q[state] = self._get_default_q_values()
        
        # Epsilon-greedy selection
        import random
        self.exploration_rate = max(self.min_exploration, 
                                   self.exploration_rate * self.exploration_decay)
        
        if random.random() < self.exploration_rate:
            # Explore: random streams (weighted towards middle range)
            return random.randint(max(2, self.default_streams - 2), 
                                 min(self.max_streams, self.default_streams + 4))
        else:
            # Exploit: use best known streams
            q_values = self.Q[state]
            best_streams = max(q_values, key=q_values.get)
            return best_streams
    
    def _get_default_q_values(self):
        """Initialize Q-values for new state."""
        # Start with neutral values, slight bias towards middle range
        q_values = {}
        for streams in range(self.min_streams, self.max_streams + 1):
            if 4 <= streams <= 8:
                q_values[streams] = 0.1  # Slight preference for moderate parallelism
            else:
                q_values[streams] = 0.0
        return q_values
    
    def update_performance(self, filesize_bytes, num_streams, throughput_mbps, elapsed_seconds):
        """
        Update Q-table based on transfer performance.
        
        Args:
            filesize_bytes: File size transferred
            num_streams: Number of streams used
            throughput_mbps: Achieved throughput in MB/s
            elapsed_seconds: Transfer duration
        """
        state = self._get_file_size_state(filesize_bytes)
        
        # Calculate reward based on throughput and efficiency
        # Higher throughput = better
        # But also consider stream efficiency (throughput per stream)
        if num_streams > 0:
            efficiency = throughput_mbps / num_streams
        else:
            efficiency = 0
        
        # Reward function:
        # - Base reward from throughput (normalized)
        # - Bonus for good efficiency (high throughput with fewer streams)
        # - Penalty for using too many streams with diminishing returns
        
        base_reward = throughput_mbps / 100.0  # Normalize (e.g., 500 MB/s -> 5.0)
        efficiency_bonus = efficiency * 0.5 if efficiency > 10 else 0
        
        # Penalty for excessive streams
        if num_streams > 12:
            stream_penalty = (num_streams - 12) * 0.2
        else:
            stream_penalty = 0
        
        reward = base_reward + efficiency_bonus - stream_penalty
        
        # Q-learning update
        if state not in self.Q:
            self.Q[state] = self._get_default_q_values()
        
        current_q = self.Q[state].get(num_streams, 0.0)
        
        # Simple Q-update (no next state since these are independent transfers)
        new_q = current_q + self.learning_rate * (reward - current_q)
        
        self.Q[state][num_streams] = new_q
        
        self.total_transfers += 1
        self.total_updates += 1
        
        print(f"📈 DCI Learning: state={state}, streams={num_streams}, "
              f"throughput={throughput_mbps:.1f} MB/s, reward={reward:.2f}")
    
    def save(self):
        """Save Q-table to disk."""
        stats = {
            'total_transfers': self.total_transfers,
            'total_updates': self.total_updates,
            'exploration_rate': self.exploration_rate,
        }
        self.storage.save(self.Q, stats)
    
    def get_stats(self):
        """Get policy statistics."""
        return {
            'model_path': self.model_path,
            'q_table_size': len(self.Q),
            'total_transfers': self.total_transfers,
            'total_updates': self.total_updates,
            'exploration_rate': self.exploration_rate,
        }
    
    def reset(self):
        """Reset Q-table (for testing)."""
        self.Q = {}
        self.total_transfers = 0
        self.total_updates = 0
        self.exploration_rate = 0.2
        print(f"🔄 DCI Policy reset")


# Convenience functions for external use
def get_optimal_streams(filesize, model_path='models/dci_model'):
    """Get optimal streams for file size."""
    policy = DCIPolicy(model_path=model_path)
    return policy.get_optimal_streams(filesize)

def update_model(filesize, num_streams, throughput, elapsed_time, model_path='models/dci_model'):
    """Update model with transfer results."""
    policy = DCIPolicy(model_path=model_path)
    policy.update_performance(filesize, num_streams, throughput, elapsed_time)
    policy.save()