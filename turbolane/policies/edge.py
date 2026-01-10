"""
turbolane/modes/client.py - Complete Client Policy
FIXED: PyTorch 2.6 compatibility + Enhanced PPO features
"""
import os
import json
import logging

logger = logging.getLogger(__name__)


class EdgePolicy:
    """
    Client-side download optimization policy.
    Supports both Q-learning and PPO algorithms via configuration.
    """
    
    def __init__(self, algorithm='ppo', config_overrides=None):
        """
        Initialize client policy with specified algorithm.
        
        Args:
            algorithm: 'qlearning' or 'ppo'
            config_overrides: Optional dict to override default hyperparameters
        """
        self.algorithm = algorithm.lower()
        config_overrides = config_overrides or {}
        
        if self.algorithm == 'qlearning':
            self._init_qlearning(config_overrides)
        elif self.algorithm == 'ppo':
            self._init_ppo(config_overrides)
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")
        
        # Storage for both algorithms
        from turbolane.rl.storage import QTableStorage
        self.storage = QTableStorage()
        
        # Load existing state
        self.load_state()
        
        logger.info(f"✅ Client policy initialized with {self.algorithm.upper()}")
    
    def _init_qlearning(self, config_overrides):
        """Initialize Q-learning agent."""
        from turbolane.rl.agent import RLAgent
        
        # Default Q-learning hyperparameters
        params = {
            'learning_rate': 0.1,
            'discount_factor': 0.8,
            'exploration_rate': 0.3,
            'min_exploration': 0.05,
            'exploration_decay': 0.995,
            'monitoring_interval': 5.0,
            'min_connections': 1,
            'max_connections': 16,
            'default_connections': 8
        }
        params.update(config_overrides)
        
        self.agent = RLAgent(**params)
    
    def _init_ppo(self, config_overrides):
        """Initialize PPO agent with enhanced implementation."""
        from turbolane.rl.ppo_agent import PPOAgent
        
        # Get PPO configuration from downloader config or use defaults
        try:
            # Try to import from downloader config
            from downloader import config as downloader_config
            base_config = downloader_config.get_ppo_config_dict()
            logger.info("✅ Loaded PPO config from downloader config")
        except (ImportError, AttributeError) as e:
            # Fallback to default PPO config if downloader not available
            logger.warning(f"Could not import downloader config: {e}, using defaults")
            base_config = self._get_default_ppo_config()
        
        # Apply any overrides
        params = base_config.copy()
        params.update(config_overrides)
        
        # Log important parameters
        logger.info(f"📊 PPO Configuration:")
        logger.info(f"   Batch Size: {params.get('batch_size', 'N/A')}")
        logger.info(f"   Learning Rate: {params.get('learning_rate', 'N/A')}")
        logger.info(f"   State History: {params.get('state_history_size', 'N/A')}")
        logger.info(f"   Entropy Decay: {params.get('entropy_decay', 'N/A')}")
        logger.info(f"   Action Map: [-2, -1, 0, +1, +2]")
        
        # Create agent
        self.agent = PPOAgent(**params)
    
    def _get_default_ppo_config(self):
        """Get default PPO configuration for fallback."""
        return {
            'state_history_size': 5,
            'learning_rate': 0.0003,
            'gamma': 0.99,
            'gae_lambda': 0.95,
            'clip_epsilon': 0.2,
            'ppo_epochs': 4,
            'batch_size': 20,
            'entropy_coef': 0.01,
            'value_coef': 0.5,
            'max_grad_norm': 0.5,
            'min_connections': 1,
            'max_connections': 16,
            'default_connections': 4,
            'exploration_steps': 100,
            'reward_scale': 1.0,
            'entropy_decay': 0.995,
            'min_entropy_coef': 0.001
        }
    
    def load_state(self):
        """Load agent state from storage."""
        try:
            if self.algorithm == 'qlearning':
                self._load_qlearning_state()
            elif self.algorithm == 'ppo':
                self._load_ppo_state()
        except Exception as e:
            logger.warning(f"Could not load saved state: {e}")
    
    def _load_qlearning_state(self):
        """Load Q-learning state."""
        Q, metadata = self.storage.load()
        
        if Q:
            self.agent.Q = Q
            logger.info(f"Loaded Q-table with {len(Q)} states")
        
        if metadata:
            self.agent.total_decisions = metadata.get('total_decisions', 0)
            self.agent.total_learning_updates = metadata.get('total_updates', 0)
            saved_exploration = metadata.get('exploration_rate', self.agent.exploration_rate)
            self.agent.exploration_rate = max(saved_exploration, self.agent.min_exploration_rate)
            
            logger.info(f"Loaded Q-learning metadata: "
                       f"{self.agent.total_decisions} decisions, "
                       f"exploration={self.agent.exploration_rate:.3f}")
    
    def _load_ppo_state(self):
        """Load PPO state - FIXED for PyTorch 2.6"""
        model_path = os.path.join(self.storage.storage_path, 'ppo_model.pt')
        
        if os.path.exists(model_path):
            try:
                # Initialize network with dummy state if needed
                if self.agent.network is None:
                    dummy_state_dim = self.agent._get_state_dim()
                    self.agent._initialize_network(dummy_state_dim)
                
                # Load with weights_only=False for backward compatibility
                self.agent.load(model_path)
                logger.info(f"✅ Loaded PPO model from {model_path}")
                
                # Load metadata if available
                metadata_path = os.path.join(self.storage.storage_path, 'ppo_metadata.json')
                if os.path.exists(metadata_path):
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)
                    logger.info(f"Loaded PPO metadata: "
                               f"{metadata.get('total_decisions', 0)} decisions, "
                               f"{metadata.get('total_updates', 0)} updates")
            except Exception as e:
                logger.warning(f"Could not load PPO model: {e}")
                logger.info("Starting with fresh PPO model")
        else:
            logger.info("No saved PPO model found, starting fresh")
    
    def decide(self, throughput, rtt, packet_loss):
        """
        Make decision about stream count.
        
        Args:
            throughput: Current throughput in Mbps
            rtt: Round-trip time in milliseconds
            packet_loss: Packet loss percentage (0-100)
        
        Returns:
            int: Desired number of streams
        """
        try:
            return self.agent.make_decision(throughput, rtt, packet_loss)
        except Exception as e:
            logger.error(f"Error in decide(): {e}", exc_info=True)
            # Fallback to current connections
            return self.agent.current_connections
    
    def learn_from_feedback(self, throughput, rtt, packet_loss):
        """
        Learn from previous decision outcome.
        
        Args:
            throughput: Current throughput in Mbps
            rtt: Round-trip time in milliseconds
            packet_loss: Packet loss percentage (0-100)
        """
        try:
            self.agent.learn_from_feedback(throughput, rtt, packet_loss)
    # Auto-save periodically
    # Use correct attribute name depending on agent type
            update_count = getattr(self.agent, 'total_updates', getattr(self.agent, 'total_learning_updates', 0))
            if update_count > 0 and update_count % 50 == 0:
                self.save()
                logger.debug(f"Auto-saved after {update_count} updates")
        except Exception as e:
            logger.error(f"Error in learn_from_feedback(): {e}", exc_info=True) 
    
    def get_stats(self):
        """
        Get policy statistics.
        
        Returns:
            dict: Statistics about agent performance
        """
        try:
            stats = self.agent.get_stats()
            stats['algorithm'] = self.algorithm
            
            # Add some summary info
            if self.algorithm == 'ppo':
                stats['buffer_status'] = f"{len(self.agent.experience_buffer)}/{self.agent.batch_size}"
                stats['exploration_rate'] = self.agent.get_exploration_rate()
            
            return stats
        except Exception as e:
            logger.error(f"Error in get_stats(): {e}", exc_info=True)
            return {'algorithm': self.algorithm, 'error': str(e)}
    
    def save(self):
        """Save policy state to disk."""
        try:
            stats = self.agent.get_stats()
            
            if self.algorithm == 'qlearning':
                self.storage.save(self.agent.Q, stats)
                logger.info(f"💾 Saved Q-table: {len(self.agent.Q)} states")
            
            elif self.algorithm == 'ppo':
                # Save neural network
                model_path = os.path.join(self.storage.storage_path, 'ppo_model.pt')
                self.agent.save(model_path)
                
                # Save metadata (stats already converted to native types by agent)
                metadata_path = os.path.join(self.storage.storage_path, 'ppo_metadata.json')
                with open(metadata_path, 'w') as f:
                    json.dump(stats, f, indent=2)
                logger.info(f"💾 Saved PPO metadata to {metadata_path}")
        
        except Exception as e:
            logger.error(f"Error saving policy: {e}", exc_info=True)
    
    def reset(self):
        """Reset policy learning (clear all learned knowledge)."""
        try:
            if self.algorithm == 'qlearning':
                self.agent.Q = {}
                self.agent.total_decisions = 0
                self.agent.total_learning_updates = 0
                self.agent.exploration_rate = 0.3  # Reset to initial
                logger.info("🔄 Reset Q-learning policy")
            
            elif self.algorithm == 'ppo':
                # Reinitialize network
                if self.agent.network is not None:
                    state_dim = self.agent._get_state_dim()
                    self.agent._initialize_network(state_dim)
                
                # Reset counters
                self.agent.total_decisions = 0
                self.agent.total_updates = 0
                
                # Reset performance stats with all new fields
                self.agent.performance_stats = {
                    'positive_rewards': 0,
                    'negative_rewards': 0,
                    'neutral_rewards': 0,
                    'total_utility': 0.0,
                    'throughput_improvements': 0,
                    'avg_reward': 0.0,
                    'best_utility': 0.0,
                    'best_throughput': 0.0,
                    'stability_score': 0.0
                }
                
                # Reset entropy coefficient
                self.agent.entropy_coef = self.agent.initial_entropy_coef
                
                # Clear histories
                self.agent.reward_history.clear()
                self.agent.utility_history.clear()
                if hasattr(self.agent, 'connection_history'):
                    self.agent.connection_history.clear()
                
                # Clear experience buffer
                self.agent.experience_buffer.clear()
                
                logger.info("🔄 Reset PPO policy")
            
            # Save reset state
            self.save()
        
        except Exception as e:
            logger.error(f"Error resetting policy: {e}", exc_info=True)
    
    def get_current_connections(self):
        """Get current number of connections."""
        return self.agent.current_connections
    
    def set_connections(self, num_connections):
        """
        Manually set number of connections.
        Useful for testing or override scenarios.
        """
        num_connections = max(
            self.agent.min_connections,
            min(self.agent.max_connections, num_connections)
        )
        self.agent.current_connections = num_connections
        logger.info(f"🔧 Manually set connections to {num_connections}")
        return num_connections
    
    def trigger_ppo_update(self):
        """
        Manually trigger a PPO update.
        Useful for testing or forcing learning.
        """
        if self.algorithm != 'ppo':
            logger.warning("Trigger update only works for PPO algorithm")
            return False
        
        try:
            buffer_size = len(self.agent.experience_buffer)
            if buffer_size >= 10:  # Minimum reasonable size
                logger.info(f"🔧 Manually triggering PPO update with {buffer_size} experiences")
                self.agent.ppo_update(force=True)
                return True
            else:
                logger.warning(f"Cannot trigger update: buffer too small ({buffer_size})")
                return False
        except Exception as e:
            logger.error(f"Error triggering PPO update: {e}")
            return False
    
    def get_buffer_status(self):
        """Get experience buffer status (PPO only)."""
        if self.algorithm != 'ppo':
            return None
        
        return {
            'size': len(self.agent.experience_buffer),
            'capacity': self.agent.batch_size,
            'percentage': (len(self.agent.experience_buffer) / self.agent.batch_size) * 100,
            'ready_for_update': len(self.agent.experience_buffer) >= self.agent.batch_size
        }
    
    def get_detailed_stats(self):
        """Get detailed statistics including learning metrics."""
        stats = self.get_stats()
        
        if self.algorithm == 'ppo':
            # Add learning rate info
            stats['learning_metrics'] = {
                'entropy_coefficient': self.agent.entropy_coef,
                'updates_completed': self.agent.total_updates,
                'buffer_utilization': f"{len(self.agent.experience_buffer)}/{self.agent.batch_size}",
            }
            
            # Add recent performance
            if len(self.agent.reward_history) > 0:
                import numpy as np
                rewards = list(self.agent.reward_history)
                stats['recent_performance'] = {
                    'avg_reward': float(np.mean(rewards)),
                    'reward_std': float(np.std(rewards)),
                    'positive_ratio': sum(1 for r in rewards if r > 0) / len(rewards)
                }
            
            if len(self.agent.utility_history) > 0:
                import numpy as np
                utilities = list(self.agent.utility_history)
                stats['recent_utility'] = {
                    'avg': float(np.mean(utilities)),
                    'max': float(np.max(utilities)),
                    'min': float(np.min(utilities))
                }
        
        return stats


# Convenience functions for common use cases

def create_qlearning_policy(**kwargs):
    """Create a Q-learning policy with custom parameters."""
    return EdgePolicy(algorithm='qlearning', config_overrides=kwargs)


def create_ppo_policy(**kwargs):
    """Create a PPO policy with custom parameters."""
    return EdgePolicy(algorithm='ppo', config_overrides=kwargs)


def load_policy(algorithm='ppo'):
    """
    Load an existing policy from disk.
    
    Args:
        algorithm: 'qlearning' or 'ppo'
    
    Returns:
        ClientPolicy: Loaded policy
    """
    policy = EdgePolicy(algorithm=algorithm)
    logger.info(f"✅ Loaded {algorithm.upper()} policy")
    return policy


def get_ppo_default_config():
    """Get default PPO configuration."""
    return {
        'state_history_size': 5,
        'learning_rate': 0.0003,
        'gamma': 0.99,
        'gae_lambda': 0.95,
        'clip_epsilon': 0.2,
        'ppo_epochs': 4,
        'batch_size': 20,
        'entropy_coef': 0.01,
        'value_coef': 0.5,
        'max_grad_norm': 0.5,
        'min_connections': 1,
        'max_connections': 16,
        'default_connections': 4,
        'exploration_steps': 100,
        'reward_scale': 1.0,
        'entropy_decay': 0.995,
        'min_entropy_coef': 0.001
    }


# Test function to verify the policy works
def test_policy():
    """Test the policy with dummy data."""
    print("🧪 Testing Client Policy...")
    
    # Test PPO
    try:
        ppo_policy = create_ppo_policy()
        
        # Simulate a few decisions
        for i in range(5):
            streams = ppo_policy.decide(
                throughput=25.0 + i * 2, 
                rtt=100.0 - i * 10, 
                packet_loss=0.1
            )
            print(f"   Decision {i+1}: {streams} streams")
        
        stats = ppo_policy.get_stats()
        print(f"\n📊 PPO Stats:")
        print(f"   Total Decisions: {stats.get('total_decisions', 0)}")
        print(f"   Current Connections: {stats.get('current_connections', 0)}")
        print(f"   Buffer: {stats.get('buffer_status', 'N/A')}")
        
        print(f"\n✅ PPO Policy test passed!")
        return True
        
    except Exception as e:
        print(f"❌ PPO Policy test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    # Run test if script is executed directly
    success = test_policy()
    if success:
        print("\n🎉 All tests passed!")
    else:
        print("\n💥 Tests failed!")