"""
turbolane/engine.py - Updated with algorithm configuration
"""

class TurboLaneEngine:
    """
    TurboLane control-plane engine.
    Supports both Q-learning and PPO algorithms.
    """
    
    def __init__(self, mode='client', algorithm='ppo'):
        """
        Initialize TurboLane engine.
        
        Args:
            mode: 'client' or 'dci' (DCI not implemented yet)
            algorithm: 'qlearning' or 'ppo'
        """
        self.mode = mode
        self.algorithm = algorithm.lower()
        
        if mode == 'client':
            from turbolane.modes.client import ClientPolicy
            self.policy = ClientPolicy(algorithm=self.algorithm)
        else:
            raise NotImplementedError(f"Mode '{mode}' not implemented yet")
        
        print(f"🤖 TurboLane Engine initialized with {self.algorithm.upper()} algorithm")
    
    def decide(self, throughput, rtt, packet_loss):
        """
        Make a decision about stream count based on network metrics.
        
        Args:
            throughput: Current throughput in Mbps
            rtt: Round-trip time in milliseconds
            packet_loss: Packet loss percentage (0-100)
        
        Returns:
            int: Desired number of streams
        """
        return self.policy.decide(throughput, rtt, packet_loss)
    
    def learn(self, throughput, rtt, packet_loss):
        """
        Learn from feedback (previous decision outcome).
        
        Args:
            throughput: Current throughput in Mbps
            rtt: Round-trip time in milliseconds
            packet_loss: Packet loss percentage (0-100)
        """
        self.policy.learn_from_feedback(throughput, rtt, packet_loss)
    
    def get_stats(self):
        """Get policy statistics."""
        return self.policy.get_stats()
    
    def save(self):
        """Save policy state."""
        self.policy.save()
    
    def reset(self):
        """Reset policy learning."""
        self.policy.reset()