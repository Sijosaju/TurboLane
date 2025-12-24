"""
turbolane/modes/client.py - Client-side RL policy wrapper
"""
from turbolane.rl.agent import RLAgent
from turbolane.rl.storage import QTableStorage


class ClientPolicy:
    """
    Client-side download optimization policy.
    Wraps the RL agent with storage management.
    """
    
    def __init__(self):
        self.agent = RLAgent(
            learning_rate=0.1,
            discount_factor=0.8,
            exploration_rate=0.3,
            min_exploration=0.05,
            exploration_decay=0.995,
            monitoring_interval=5.0,
            min_connections=1,
            max_connections=16,
            default_connections=8
        )
        
        self.storage = QTableStorage()
        
        # Load existing Q-table
        Q, metadata = self.storage.load()
        self.agent.Q = Q
        
        if metadata:
            self.agent.total_decisions = metadata.get('total_decisions', 0)
            self.agent.total_learning_updates = metadata.get('total_updates', 0)
            saved_exploration = metadata.get('exploration_rate', self.agent.exploration_rate)
            self.agent.exploration_rate = max(saved_exploration, self.agent.min_exploration_rate)
    
    def decide(self, throughput, rtt, packet_loss):
        """Make decision about stream count."""
        return self.agent.make_decision(throughput, rtt, packet_loss)
    
    def learn_from_feedback(self, throughput, rtt, packet_loss):
        """Learn from previous decision outcome."""
        self.agent.learn_from_feedback(throughput, rtt, packet_loss)
        
        # Auto-save every 50 updates
        if self.agent.total_learning_updates % 50 == 0:
            self.save()
    
    def get_stats(self):
        """Get policy statistics."""
        return self.agent.get_stats()
    
    def save(self):
        """Save policy state."""
        stats = self.agent.get_stats()
        self.storage.save(self.agent.Q, stats)
    
    def reset(self):
        """Reset policy learning."""
        self.agent.Q = {}
        self.save()