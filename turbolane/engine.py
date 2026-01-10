"""
turbolane/engine.py - Unified TurboLane Engine
Supports both Edge (client) and Federated (DCI) modes.
"""

import logging

logger = logging.getLogger(__name__)


class TurboLaneEngine:
    """
    TurboLane control-plane engine.
    Supports both Q-learning and PPO algorithms with pluggable policies.
    """
    
    def __init__(self, mode='client', algorithm='ppo', **policy_kwargs):
        """
        Initialize TurboLane engine.
        
        Args:
            mode: 'client' (EdgePolicy) or 'dci' (FederatedPolicy)
            algorithm: 'qlearning' or 'ppo'
            **policy_kwargs: Additional arguments passed to policy constructor
        """
        self.mode = mode
        self.algorithm = algorithm.lower()
        
        if mode == 'client':
            from turbolane.policies import EdgePolicy
            self.policy = EdgePolicy(algorithm=self.algorithm, config_overrides=policy_kwargs)
            logger.info(f"🤖 TurboLane Engine initialized: Edge mode ({self.algorithm.upper()})")
            
        elif mode == 'dci':
            from turbolane.policies import FederatedPolicy
            
            # Default DCI parameters
            dci_defaults = {
                'agent_type': self.algorithm,
                'model_dir': 'models/dci',
                'state_size': 5,
                'action_size': 3,
                'learning_rate': 0.001 if self.algorithm == 'ppo' else 0.1,
                'discount_factor': 0.99 if self.algorithm == 'ppo' else 0.8,
                'epsilon': 0.3,
                'epsilon_decay': 0.995,
                'epsilon_min': 0.05,
                'min_connections': 1,
                'max_connections': 32,
                'default_connections': 4
            }
            
            # Override with user-provided kwargs
            dci_defaults.update(policy_kwargs)
            
            self.policy = FederatedPolicy(**dci_defaults)
            logger.info(f"🤖 TurboLane Engine initialized: DCI mode ({self.algorithm.upper()})")
            
        else:
            raise ValueError(f"Unknown mode '{mode}'. Use 'client' or 'dci'.")
    
    # ===================================================================
    # CLIENT MODE METHODS (for downloader)
    # ===================================================================
    
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
        if self.mode == 'client':
            return self.policy.decide(throughput, rtt, packet_loss)
        else:
            raise NotImplementedError(
                "decide() is only available in 'client' mode. "
                "Use select_action() for DCI mode."
            )
    
    def learn(self, throughput, rtt, packet_loss):
        """
        Learn from feedback (previous decision outcome).
        
        Args:
            throughput: Current throughput in Mbps
            rtt: Round-trip time in milliseconds
            packet_loss: Packet loss percentage (0-100)
        """
        if self.mode == 'client':
            self.policy.learn_from_feedback(throughput, rtt, packet_loss)
        else:
            raise NotImplementedError(
                "learn() is only available in 'client' mode. "
                "Use update() for DCI mode."
            )
    
    # ===================================================================
    # DCI MODE METHODS (for dci/client.py)
    # ===================================================================
    
    def select_action(self, state, current_connections, explore=True):
        """
        Select action for DCI mode (state-based decision).
        
        Args:
            state: Current environment state tuple
            current_connections: Current number of TCP connections
            explore: Whether to use exploration (training mode)
            
        Returns:
            int: New number of connections (action applied)
        """
        if self.mode == 'dci':
            return self.policy.select_action(state, current_connections, explore)
        else:
            raise NotImplementedError(
                "select_action() is only available in 'dci' mode. "
                "Use decide() for client mode."
            )
    
    def update(self, state, action, reward, next_state, done=False):
        """
        Update policy based on transition (DCI mode).
        
        Args:
            state: Current state
            action: Action taken
            reward: Reward received
            next_state: Resulting state
            done: Episode termination flag
        """
        if self.mode == 'dci':
            self.policy.update(state, action, reward, next_state, done)
        else:
            raise NotImplementedError(
                "update() is only available in 'dci' mode. "
                "Use learn() for client mode."
            )
    
    def train_step(self):
        """
        Execute one training step (PPO only, DCI mode).
        
        Returns:
            Training loss if applicable, None otherwise
        """
        if self.mode == 'dci':
            return self.policy.train_step()
        else:
            raise NotImplementedError("train_step() is only available in 'dci' mode.")
    
    # ===================================================================
    # COMMON METHODS (both modes)
    # ===================================================================
    
    def get_stats(self):
        """Get policy statistics."""
        return self.policy.get_stats()
    
    def save(self):
        """Save policy state."""
        self.policy.save()
    
    def reset(self):
        """Reset policy learning."""
        self.policy.reset()
    
    def get_current_connections(self):
        """Get current number of connections."""
        return self.policy.agent.current_connections
    
    def set_connections(self, num_connections):
        """Manually set number of connections."""
        if hasattr(self.policy, 'set_connections'):
            return self.policy.set_connections(num_connections)
        else:
            # Fallback for FederatedPolicy
            num_connections = max(
                self.policy.agent.min_connections,
                min(self.policy.agent.max_connections, num_connections)
            )
            self.policy.agent.current_connections = num_connections
            return num_connections
