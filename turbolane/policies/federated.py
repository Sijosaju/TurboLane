"""
Federated Policy for Data Center Environments
Wraps RL agents for high-bandwidth, stable network transfers in DCI.
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional

from turbolane.rl.agent import RLAgent
from turbolane.rl.ppo_agent import PPOAgent
from turbolane.rl.storage import QTableStorage

logger = logging.getLogger(__name__)


class FederatedPolicy:
    """
    Policy wrapper for federated/data-center environments.
    Encapsulates agent selection, persistence, and decision logic.
    """
    
    def __init__(
        self,
        agent_type: str = "ppo",
        model_dir: str = "models/dci",
        state_size: int = 5,
        action_size: int = 3,
        learning_rate: float = 0.001,
        discount_factor: float = 0.99,
        epsilon: float = 0.3,
        epsilon_decay: float = 0.995,
        epsilon_min: float = 0.05,
        min_connections: int = 1,
        max_connections: int = 32,
        default_connections: int = 4
    ):
        """
        Initialize federated policy with specified agent.
        
        Args:
            agent_type: "q_learning" or "ppo"
            model_dir: Directory for model persistence
            state_size: Size of state history (for PPO)
            action_size: Number of actions (typically 3)
            learning_rate: Learning rate for the agent
            discount_factor: Gamma for future rewards
            epsilon: Initial exploration rate (Q-learning only)
            epsilon_decay: Exploration decay rate (Q-learning only)
            epsilon_min: Minimum exploration rate (Q-learning only)
            min_connections: Minimum number of connections
            max_connections: Maximum number of connections
            default_connections: Initial number of connections
        """
        self.agent_type = agent_type.lower()
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize agent based on type
        if self.agent_type == "q_learning" or self.agent_type == "qlearning":
            self.agent = RLAgent(
                min_connections=min_connections,
                max_connections=max_connections,
                default_connections=default_connections,
                learning_rate=learning_rate,
                discount_factor=discount_factor,
                epsilon=epsilon,
                epsilon_decay=epsilon_decay,
                epsilon_min=epsilon_min
            )
            self.storage = QTableStorage(str(self.model_dir / "q_table.pkl"))
            self._load_q_state()
            
        elif self.agent_type == "ppo":
            # Create PPO agent with parameters matching PPOAgent's expected signature
            # Based on edge.py's _get_default_ppo_config()
            ppo_params = {
                'state_history_size': state_size,  # ← Note: state_history_size, not state_size
                'learning_rate': learning_rate,
                'gamma': discount_factor,
                'gae_lambda': 0.95,
                'clip_epsilon': 0.2,
                'ppo_epochs': 4,
                'batch_size': 20,
                'entropy_coef': 0.01,
                'value_coef': 0.5,
                'max_grad_norm': 0.5,
                'min_connections': min_connections,
                'max_connections': max_connections,
                'default_connections': default_connections,
                'exploration_steps': 100,
                'reward_scale': 1.0,
                'entropy_decay': 0.995,
                'min_entropy_coef': 0.001
            }
            
            self.agent = PPOAgent(**ppo_params)
            self.storage = None
            self._load_ppo_state()
            
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")
        
        logger.info(f"FederatedPolicy initialized with {self.agent_type} agent")
    
    def _load_q_state(self) -> None:
        """Load Q-learning state from disk."""
        try:
            Q, metadata = self.storage.load()
            if Q:
                self.agent.Q = Q
                logger.info(f"Loaded Q-table with {len(Q)} states")
        except Exception as e:
            logger.info(f"Starting with fresh Q-table: {e}")
    
    def _load_ppo_state(self) -> None:
        """Load PPO model from disk."""
        model_path = self.model_dir / "ppo_model.pt"
        if model_path.exists():
            try:
                self.agent.load(str(model_path))
                logger.info("Loaded existing PPO model")
            except Exception as e:
                logger.warning(f"Failed to load PPO model: {e}")
        else:
            logger.info("Starting with fresh PPO model")
    
    def select_action(
        self,
        state: tuple,
        current_connections: int,
        explore: bool = True
    ) -> int:
        """
        Select action based on current state.
        
        Args:
            state: Current environment state tuple
            current_connections: Current number of TCP connections
            explore: Whether to use exploration (training mode)
            
        Returns:
            New number of connections (action applied)
        """
        try:
            if self.agent_type in ["q_learning", "qlearning"]:
                action = self.agent.choose_action(state, explore=explore)
            else:  # PPO
                action = self.agent.select_action(state, explore=explore)
            
            # Apply action to current connections
            if action == 0:  # Decrease
                return max(self.agent.min_connections, current_connections - 1)
            elif action == 1:  # Maintain
                return current_connections
            elif action == 2:  # Increase
                return min(current_connections + 1, self.agent.max_connections)
            else:
                logger.warning(f"Invalid action {action}, maintaining connections")
                return current_connections
                
        except Exception as e:
            logger.error(f"Action selection failed: {e}")
            return current_connections  # Safe fallback
    
    def update(
        self,
        state: tuple,
        action: int,
        reward: float,
        next_state: tuple,
        done: bool = False
    ) -> None:
        """
        Update policy based on transition.
        
        Args:
            state: Current state
            action: Action taken
            reward: Reward received
            next_state: Resulting state
            done: Episode termination flag
        """
        try:
            if self.agent_type in ["q_learning", "qlearning"]:
                self.agent.update(state, action, reward, next_state)
            else:  # PPO
                self.agent.store_transition(state, action, reward, next_state, done)
                
        except Exception as e:
            logger.error(f"Policy update failed: {e}")
    
    def train_step(self) -> Optional[float]:
        """
        Execute one training step (PPO only).
        
        Returns:
            Training loss if applicable, None otherwise
        """
        if self.agent_type == "ppo":
            try:
                return self.agent.train_step()
            except Exception as e:
                logger.error(f"Training step failed: {e}")
                return None
        return None
    
    def save(self) -> None:
        """Persist policy state to disk."""
        try:
            if self.agent_type in ["q_learning", "qlearning"]:
                stats = {
                    'total_decisions': getattr(self.agent, 'total_decisions', 0),
                    'total_updates': getattr(self.agent, 'total_learning_updates', 0)
                }
                self.storage.save(self.agent.Q, stats)
                logger.info("Q-table saved")
            else:  # PPO
                model_path = self.model_dir / "ppo_model.pt"
                self.agent.save(str(model_path))
                logger.info("PPO model saved")
        except Exception as e:
            logger.error(f"Failed to save policy: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get policy statistics for monitoring.
        
        Returns:
            Dictionary of policy metrics
        """
        stats = {
            "agent_type": self.agent_type,
            "epsilon": getattr(self.agent, 'epsilon', None),
        }
        
        if self.agent_type in ["q_learning", "qlearning"]:
            stats["q_table_size"] = len(getattr(self.agent, 'Q', {}))
        elif self.agent_type == "ppo":
            stats["buffer_size"] = len(getattr(self.agent, 'experience_buffer', []))
            
        return stats


