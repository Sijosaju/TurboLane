"""
turbolane/engine.py - TurboLane Control-Plane Engine
Thin wrapper around RL agent for decision-making only
"""


class TurboLaneEngine:
    """
    TurboLane control-plane engine.
    Provides decision-making interface without touching data path.
    """
    
    def __init__(self, mode='client'):
        """
        Initialize TurboLane engine.
        
        Args:
            mode: 'client' or 'dci' (DCI not implemented yet)
        """
        self.mode = mode
        
        if mode == 'client':
            from turbolane.modes.client import ClientPolicy
            self.policy = ClientPolicy()
        else:
            raise NotImplementedError(f"Mode '{mode}' not implemented yet")
    
    def decide(self, throughput, rtt, packet_loss):
        """
        Make a decision about stream count based on network metrics.
        This is fast and non-blocking - just returns a number.
        
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