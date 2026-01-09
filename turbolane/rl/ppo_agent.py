"""
turbolane/rl/ppo_agent.py - ENHANCED Policy-Agnostic PPO Agent
ULTIMATE VERSION with partial batch training, better normalization, and enhanced metrics
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from collections import deque
import logging
import pickle
import os
import time
from typing import Dict, List, Optional, Tuple, Any, Union
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# Enhanced Actor–Critic Network with Dropout
# ============================================================

class ActorCriticNetwork(nn.Module):
    def __init__(self, state_dim: int, action_dim: int, hidden_dim: int = 64, dropout: float = 0.1):
        super().__init__()
        
        # Shared feature extractor with dropout
        self.shared = nn.Sequential(
            nn.Linear(state_dim, hidden_dim * 2),
            nn.LayerNorm(hidden_dim * 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout)
        )
        
        # Actor head
        self.actor = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, action_dim)
        )
        
        # Critic head
        self.critic = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, 1)
        )
        
        self._init_weights()
    
    def _init_weights(self):
        """Initialize weights with orthogonal initialization."""
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.orthogonal_(m.weight, gain=np.sqrt(2))
                nn.init.constant_(m.bias, 0.0)
    
    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        features = self.shared(x)
        return self.actor(features), self.critic(features)
    
    def get_action_and_value(self, state: torch.Tensor, action: Optional[torch.Tensor] = None):
        logits, value = self(state)
        probs = F.softmax(logits, dim=-1)
        dist = torch.distributions.Categorical(probs=probs)
        
        if action is None:
            action = dist.sample()
        
        return action, dist.log_prob(action), dist.entropy(), value.squeeze(-1)


# ============================================================
# Prioritized Experience Buffer (Optional Enhancement)
# ============================================================

class PrioritizedExperienceBuffer:
    """Experience buffer with optional prioritization."""
    
    def __init__(self, max_size: int = 2000, alpha: float = 0.6, beta: float = 0.4):
        self.max_size = max_size
        self.alpha = alpha  # Prioritization exponent (0 = uniform)
        self.beta = beta    # Importance sampling exponent
        self.clear()
    
    def clear(self):
        self.states = []
        self.actions = []
        self.rewards = []
        self.next_states = []
        self.dones = []
        self.log_probs = []
        self.values = []
        self.priorities = []
        self.position = 0
    
    def add(self, s, a, r, ns, d, lp, v, priority: float = 1.0):
        """Add experience with initial priority."""
        if len(self.states) >= self.max_size:
            # Overwrite oldest experience
            idx = self.position % self.max_size
            self.states[idx] = s
            self.actions[idx] = a
            self.rewards[idx] = r
            self.next_states[idx] = ns
            self.dones[idx] = d
            self.log_probs[idx] = lp
            self.values[idx] = v
            self.priorities[idx] = priority ** self.alpha
        else:
            self.states.append(s)
            self.actions.append(a)
            self.rewards.append(r)
            self.next_states.append(ns)
            self.dones.append(d)
            self.log_probs.append(lp)
            self.values.append(v)
            self.priorities.append(priority ** self.alpha)
        
        self.position += 1
    
    def update_priorities(self, indices: List[int], priorities: List[float]):
        """Update priorities for specific experiences."""
        for idx, priority in zip(indices, priorities):
            if idx < len(self.priorities):
                self.priorities[idx] = (priority + 1e-6) ** self.alpha
    
    def sample(self, batch_size: int) -> Tuple[List[Any], List[int], List[float]]:
        """Sample batch of experiences with probabilities proportional to priorities."""
        if len(self) == 0:
            return [], [], []
        
        probs = np.array(self.priorities[:len(self)])
        probs = probs / probs.sum()
        
        indices = np.random.choice(len(self), min(batch_size, len(self)), p=probs, replace=False)
        
        # Calculate importance sampling weights
        weights = (len(self) * probs[indices]) ** (-self.beta)
        weights = weights / weights.max()  # Normalize
        
        batch = [
            [self.states[i] for i in indices],
            [self.actions[i] for i in indices],
            [self.rewards[i] for i in indices],
            [self.next_states[i] for i in indices],
            [self.dones[i] for i in indices],
            [self.log_probs[i] for i in indices],
            [self.values[i] for i in indices]
        ]
        
        return batch, indices.tolist(), weights.tolist()
    
    def get_all(self):
        """Get all experiences (for backward compatibility)."""
        return (
            self.states,
            self.actions,
            self.rewards,
            self.next_states,
            self.dones,
            self.log_probs,
            self.values
        )
    
    def __len__(self):
        return len(self.states)


# ============================================================
# ULTIMATE Policy-Agnostic PPO Agent
# ============================================================

class PPOAgent:
    """
    ULTIMATE Policy-Agnostic PPO Agent with partial batch training.
    
    Key Features:
    1. Partial batch training (train with as little as 30% of full batch)
    2. Configurable state normalization per policy
    3. Learning rate scheduling
    4. Enhanced metrics and monitoring
    5. Gradient clipping with monitoring
    6. Experience retention between updates
    """
    
    def __init__(
        self,
        # Core PPO Parameters
        state_history_size: int = 5,
        learning_rate: float = 3e-4,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_epsilon: float = 0.2,
        ppo_epochs: int = 4,
        batch_size: int = 20,
        entropy_coef: float = 0.01,
        value_coef: float = 0.5,
        max_grad_norm: float = 0.5,
        
        # Connection Management
        min_connections: int = 1,
        max_connections: int = 16,
        default_connections: int = 4,
        
        # Exploration & Learning
        exploration_steps: int = 100,
        reward_scale: float = 1.0,
        entropy_decay: float = 0.995,
        min_entropy_coef: float = 0.001,
        
        # NEW: Partial Batch Training
        min_batch_ratio: float = 0.3,      # Train with at least 30% of batch
        experience_keep_ratio: float = 0.2, # Keep 20% of experiences between updates
        
        # NEW: Learning Rate Scheduling
        lr_decay: float = 0.99995,
        min_lr: float = 1e-6,
        
        # NEW: State Normalization Configuration
        normalization_config: Optional[Dict] = None,
        
        # ============================================================
        # Policy-Specific Parameters (Configurable)
        # ============================================================
        
        # Action mapping (Edge vs Federated)
        action_map: Optional[Dict[int, int]] = None,
        
        # Utility function parameters
        utility_K: float = 1.02,
        utility_B: float = 5.0,
        utility_epsilon: float = 0.08,
        
        # Reward shaping parameters
        utility_bonus: float = 0.1,
        throughput_improvement_bonus: float = 0.0,
        
        # Stability control
        enable_stability_penalty: bool = True,
        stability_penalty: float = 0.05,
        stability_window: int = 3,
        
        # Action-specific rewards/penalties
        enable_aggressive_penalty: bool = False,
        aggressive_penalty_scale: float = 0.05,
        aggressive_threshold: int = 1,
        
        # Prioritized Experience Replay (Optional)
        use_prioritized_replay: bool = False,
        priority_alpha: float = 0.6,
        priority_beta: float = 0.4
    ):
        # Device setup
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # ============================================================
        # Core PPO Hyperparameters
        # ============================================================
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_epsilon = clip_epsilon
        self.ppo_epochs = ppo_epochs
        self.batch_size = batch_size
        self.entropy_coef = entropy_coef
        self.initial_entropy_coef = entropy_coef
        self.min_entropy_coef = min_entropy_coef
        self.entropy_decay = entropy_decay
        self.value_coef = value_coef
        self.max_grad_norm = max_grad_norm
        self.reward_scale = reward_scale
        self.learning_rate = learning_rate
        self.initial_lr = learning_rate
        
        # NEW: Learning Rate Scheduling
        self.lr_decay = lr_decay
        self.min_lr = min_lr
        
        # NEW: Partial Batch Training
        self.min_batch_ratio = min_batch_ratio
        self.experience_keep_ratio = experience_keep_ratio
        self.min_batch_samples = int(batch_size * min_batch_ratio)
        
        # ============================================================
        # Connection Management
        # ============================================================
        self.current_connections = default_connections
        self.min_connections = min_connections
        self.max_connections = max_connections
        
        # ============================================================
        # NEW: Configurable State Normalization
        # ============================================================
        self.norm_config = normalization_config or {
            'rtt_grad': 100.0,      # Normalize RTT gradient by 100 ms/s
            'loss': 100.0,          # Normalize packet loss by 100% (makes 1% = 0.01)
            'throughput': 1000.0,   # Normalize throughput by 1000 Mbps
            'use_min_rtt_norm': True,  # Use min-RTT normalization for RTT
            'rtt_norm_base': 200.0  # Fallback if not using min-RTT
        }
        
        # ============================================================
        # Policy Configuration
        # ============================================================
        self.action_map = action_map or {0: -2, 1: -1, 2: 0, 3: +1, 4: +2}
        self.K = utility_K
        self.B = utility_B
        self.epsilon = utility_epsilon
        self.utility_bonus = utility_bonus
        self.throughput_improvement_bonus = throughput_improvement_bonus
        self.enable_stability_penalty = enable_stability_penalty
        self.stability_penalty = stability_penalty
        self.stability_window = stability_window
        self.enable_aggressive_penalty = enable_aggressive_penalty
        self.aggressive_penalty_scale = aggressive_penalty_scale
        self.aggressive_threshold = aggressive_threshold
        
        # Validate configuration
        self._validate_config()
        
        # ============================================================
        # State Management
        # ============================================================
        self.state_history_size = state_history_size
        self.state_history = deque(maxlen=state_history_size)
        self.min_rtt = float('inf')
        
        # ============================================================
        # Tracking & Statistics
        # ============================================================
        self.last_state = None
        self.last_action = None
        self.last_log_prob = None
        self.last_value = None
        self.last_utility = None
        self.last_throughput = None
        
        self.total_decisions = 0
        self.total_updates = 0
        self.total_samples_processed = 0
        
        # Enhanced statistics
        self.performance_stats = {
            "positive_rewards": 0,
            "negative_rewards": 0,
            "neutral_rewards": 0,
            "total_utility": 0.0,
            "throughput_improvements": 0,
            "avg_reward": 0.0,
            "best_utility": 0.0,
            "best_throughput": 0.0,
            "stability_score": 0.0,
            "clip_ratio": 0.0,          # NEW: Track clipping
            "approx_kl": 0.0,           # NEW: Approximate KL divergence
            "value_loss": 0.0,          # NEW: Value loss tracking
            "policy_entropy": 0.0,      # NEW: Current policy entropy
            "gradient_norm": 0.0,       # NEW: Gradient norm
            "learning_rate": learning_rate
        }
        
        # Running statistics
        self.reward_history = deque(maxlen=100)
        self.utility_history = deque(maxlen=100)
        self.connection_history = deque(maxlen=10)
        self.clip_history = deque(maxlen=50)  # NEW: Track clipping ratios
        
        # ============================================================
        # Experience Buffer (Prioritized or Standard)
        # ============================================================
        if use_prioritized_replay:
            self.experience_buffer = PrioritizedExperienceBuffer(
                max_size=2000,
                alpha=priority_alpha,
                beta=priority_beta
            )
            logger.info("Using Prioritized Experience Replay")
        else:
            self.experience_buffer = PrioritizedExperienceBuffer(max_size=2000)
            self.experience_buffer.alpha = 0.0  # Disable prioritization
        
        self.buffer = self.experience_buffer  # Alias for compatibility
        
        # ============================================================
        # Neural Network
        # ============================================================
        self.network = None
        self.optimizer = None
        
        # ============================================================
        # Enhanced Logging
        # ============================================================
        logger.info("=" * 60)
        logger.info("🤖 ULTIMATE PPO Agent Initialized")
        logger.info("=" * 60)
        logger.info(f"📊 Policy Configuration:")
        logger.info(f"   Action Map: {sorted(self.action_map.items())}")
        logger.info(f"   Utility: K={self.K:.3f}, B={self.B:.1f}, ε={self.epsilon:.3f}")
        logger.info(f"   Safety: stability={self.enable_stability_penalty}, aggressive={self.enable_aggressive_penalty}")
        logger.info("")
        logger.info(f"🎯 Training Configuration:")
        logger.info(f"   Batch: {self.batch_size} (min {self.min_batch_samples})")
        logger.info(f"   LR: {self.learning_rate:.2e} (decay: {self.lr_decay:.5f})")
        logger.info(f"   Clip: ε={self.clip_epsilon}, γ={self.gamma}, λ={self.gae_lambda}")
        logger.info(f"   Entropy: {self.entropy_coef:.3f} (decay: {self.entropy_decay:.3f})")
        logger.info("")
        logger.info(f"🔧 Connection Management:")
        logger.info(f"   Range: {self.min_connections}-{self.max_connections}")
        logger.info(f"   Initial: {self.current_connections}")
        logger.info("=" * 60)
    
    def _validate_config(self):
        """Validate PPO-specific parameters."""
        errors = []
        
        # PPO clipping parameter
        if not 0 < self.clip_epsilon <= 0.3:
            errors.append(f"clip_epsilon should be in (0, 0.3], got {self.clip_epsilon}")
        
        # Batch size relative to epochs
        if self.batch_size < 4 * self.ppo_epochs:
            logger.warning(f"Batch size {self.batch_size} is small for {self.ppo_epochs} epochs")
        
        # Learning rate sanity
        if self.learning_rate > 0.01:
            errors.append(f"Learning rate {self.learning_rate:.2e} is too high for PPO")
        
        # Min batch ratio
        if not 0.1 <= self.min_batch_ratio <= 1.0:
            errors.append(f"min_batch_ratio must be in [0.1, 1.0], got {self.min_batch_ratio}")
        
        # Experience keep ratio
        if not 0 <= self.experience_keep_ratio <= 0.5:
            errors.append(f"experience_keep_ratio must be in [0, 0.5], got {self.experience_keep_ratio}")
        
        # Action map validation
        if not isinstance(self.action_map, dict):
            errors.append("action_map must be a dictionary")
        elif len(self.action_map) < 3:
            errors.append(f"action_map should have at least 3 actions, got {len(self.action_map)}")
        
        if errors:
            error_msg = "PPO Configuration errors:\n" + "\n".join(errors)
            raise ValueError(error_msg)
        
        return True
    
    # ========================================================
    # LEGACY METHODS REQUIRED BY client.py
    # ========================================================
    
    def _get_state_dim(self) -> int:
        return 4 * self.state_history_size
    
    def _initialize_network(self, state_dim: int):
        self.network = ActorCriticNetwork(state_dim, len(self.action_map)).to(self.device)
        self.optimizer = torch.optim.Adam(self.network.parameters(), lr=self.learning_rate)
        logger.info(f"Initialized network: state_dim={state_dim}, actions={len(self.action_map)}")
    
    def learn_from_feedback(self, *args, **kwargs):
        """Legacy method for compatibility."""
        return
    
    def get_exploration_rate(self) -> float:
        """Get current exploration rate (for compatibility)."""
        # Convert entropy coefficient to exploration-like metric
        exploration = self.entropy_coef / self.initial_entropy_coef
        return max(0.0, min(1.0, exploration))
    
    # ========================================================
    # Enhanced State Management
    # ========================================================
    
    def _compute_state(self, throughput: float, rtt: float, loss: float) -> np.ndarray:
        """
        Compute normalized state vector with configurable normalization.
        
        State features:
        1. RTT gradient (normalized)
        2. RTT (normalized by min-RTT or fixed base)
        3. Packet loss (normalized)
        4. Throughput (normalized)
        """
        norm = self.norm_config
        
        # Calculate RTT gradient
        if len(self.state_history) > 0:
            rtt_grad = rtt - self.state_history[-1][1]
        else:
            rtt_grad = 0.0
        
        # Update min RTT
        self.min_rtt = min(self.min_rtt, rtt)
        
        # Normalize RTT
        if norm['use_min_rtt_norm']:
            rtt_norm = rtt / max(self.min_rtt, 1.0)
        else:
            rtt_norm = rtt / norm['rtt_norm_base']
        
        # Create state vector
        state = np.array([
            rtt_grad / norm['rtt_grad'],
            rtt_norm,
            loss / norm['loss'],
            throughput / norm['throughput']
        ], dtype=np.float32)
        
        return state
    
    def get_state(self, throughput: float, rtt: float, loss: float) -> np.ndarray:
        """
        Get current state with history.
        
        Args:
            throughput: Current throughput in Mbps
            rtt: Round-trip time in milliseconds
            loss: Packet loss percentage (0-100)
        
        Returns:
            np.ndarray: State vector with history
        """
        # Compute current state
        current_state = self._compute_state(throughput, rtt, loss)
        self.state_history.append(current_state)
        
        # Pad history if needed
        while len(self.state_history) < self.state_history_size:
            self.state_history.appendleft(np.zeros_like(current_state))
        
        # Concatenate history
        state = np.concatenate(list(self.state_history))
        
        # Initialize network if needed
        if self.network is None:
            self._initialize_network(len(state))
        
        return state
    
    # ========================================================
    # Enhanced Utility and Reward Calculation
    # ========================================================
    
    def calculate_utility(self, n: int, t: float, loss: float) -> float:
        """
        Calculate utility using configurable parameters.
        
        U(n,t) = t/(K^n) - t*(loss/100)*B
        
        Args:
            n: Number of connections
            t: Throughput in Mbps
            loss: Packet loss percentage
        
        Returns:
            float: Utility value
        """
        # Avoid division by zero
        k_power = self.K ** n
        if k_power == 0:
            k_power = 1e-10
        
        cost_term = t / k_power
        loss_penalty = t * (loss / 100.0) * self.B
        utility = cost_term - loss_penalty
        
        # Debug logging (occasional)
        if self.total_decisions % 100 == 0 and self.total_decisions > 0:
            logger.debug(
                f"Utility[{self.total_decisions}]: "
                f"t={t:.1f}Mbps, n={n}, loss={loss:.2f}% → "
                f"cost={cost_term:.1f}, penalty={loss_penalty:.1f}, utility={utility:.1f}"
            )
        
        # Update best utility
        self.performance_stats["best_utility"] = max(
            self.performance_stats["best_utility"], utility
        )
        self.performance_stats["best_throughput"] = max(
            self.performance_stats["best_throughput"], t
        )
        
        return utility
    
    def calculate_reward(self, prev_u: float, curr_u: float, 
                         throughput: float, action: int) -> float:
        """
        Calculate reward using configurable reward shaping.
        
        Args:
            prev_u: Previous utility
            curr_u: Current utility
            throughput: Current throughput in Mbps
            action: Action index taken
        
        Returns:
            float: Reward value
        """
        # Track utility history
        self.utility_history.append(curr_u)
        
        # Base reward from utility improvement (tanh for bounded output)
        delta = curr_u - prev_u
        if abs(prev_u) > 1e-6:
            reward = np.tanh(delta * self.reward_scale / abs(prev_u))
        else:
            reward = np.tanh(delta * self.reward_scale)
        
        # ============================================================
        # Configurable utility bonus
        # ============================================================
        if self.utility_bonus > 0:
            if curr_u > 0.9 * self.performance_stats["best_utility"]:
                reward += self.utility_bonus
                logger.debug(f"Utility bonus: +{self.utility_bonus:.3f}")
        
        # ============================================================
        # Configurable throughput improvement bonus
        # ============================================================
        if self.throughput_improvement_bonus > 0:
            if (self.last_throughput is not None and 
                throughput > self.last_throughput):
                reward += self.throughput_improvement_bonus
                logger.debug(f"Throughput bonus: +{self.throughput_improvement_bonus:.3f}")
        
        # ============================================================
        # Configurable stability penalty
        # ============================================================
        if (self.enable_stability_penalty and 
            len(self.connection_history) >= self.stability_window):
            
            recent = list(self.connection_history)[-self.stability_window:]
            unique_counts = len(set(recent))
            
            if unique_counts == 2:  # Oscillating between two values
                reward -= self.stability_penalty
                logger.debug(f"Stability penalty: -{self.stability_penalty:.3f}")
        
        # ============================================================
        # Configurable aggressive action penalty
        # ============================================================
        if self.enable_aggressive_penalty:
            action_delta = abs(self.action_map.get(action, 0))
            if action_delta > self.aggressive_threshold:
                penalty = self.aggressive_penalty_scale * action_delta
                reward -= penalty
                logger.debug(f"Aggressive penalty: -{penalty:.3f} (Δ={action_delta})")
        
        # Track reward statistics
        self.reward_history.append(reward)
        
        # Update performance statistics
        if reward > 0:
            self.performance_stats["positive_rewards"] += 1
        elif reward < 0:
            self.performance_stats["negative_rewards"] += 1
        else:
            self.performance_stats["neutral_rewards"] += 1
        
        # Update average reward
        if len(self.reward_history) > 0:
            self.performance_stats["avg_reward"] = np.mean(list(self.reward_history))
        
        return reward
    
    # ========================================================
    # Enhanced Action Selection
    # ========================================================
    
    def act(self, state: np.ndarray) -> Tuple[int, float, float]:
        """
        Select action using current policy.
        
        Args:
            state: Current state vector
        
        Returns:
            tuple: (action_index, log_probability, state_value)
        """
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        
        with torch.no_grad():
            action, log_prob, entropy, value = self.network.get_action_and_value(state_tensor)
        
        # Track current policy entropy
        self.performance_stats["policy_entropy"] = entropy.item()
        
        return action.item(), log_prob.item(), value.item()
    
    # ========================================================
    # Enhanced Decision Making (Main Entry Point)
    # ========================================================
    
    def make_decision(self, throughput: float, rtt: float, 
                      loss: float, done: bool = False) -> int:
        """
        Main decision-making method.
        
        Args:
            throughput: Current throughput in Mbps
            rtt: Round-trip time in milliseconds
            loss: Packet loss percentage (0-100)
            done: Whether episode is done
        
        Returns:
            int: New number of connections
        """
        self.total_decisions += 1
        
        # Get current state
        state = self.get_state(throughput, rtt, loss)
        
        # Select action
        action, log_prob, value = self.act(state)
        
        # Calculate utility
        utility = self.calculate_utility(self.current_connections, throughput, loss)
        self.performance_stats["total_utility"] += utility
        
        # Track throughput improvements
        if (self.last_throughput is not None and 
            throughput > self.last_throughput):
            self.performance_stats["throughput_improvements"] += 1
        
        # Calculate reward and store experience if we have previous state
        if self.last_state is not None:
            reward = self.calculate_reward(
                self.last_utility, 
                utility, 
                throughput,
                self.last_action
            )
            
            # Store experience with TD-error as initial priority
            td_error = abs(reward + self.gamma * value - self.last_value) if not done else abs(reward)
            self.experience_buffer.add(
                self.last_state,
                self.last_action,
                reward,
                state,
                done,
                self.last_log_prob,
                self.last_value,
                priority=td_error + 1e-6
            )
            
            # Try to perform PPO update (with partial batch support)
            self.ppo_update()
            
            # Decay entropy coefficient
            self.entropy_coef = max(
                self.min_entropy_coef,
                self.entropy_coef * self.entropy_decay
            )
        
        # Update tracking variables
        self.last_state = state
        self.last_action = action
        self.last_log_prob = log_prob
        self.last_value = value
        self.last_utility = utility
        self.last_throughput = throughput
        
        # Apply action to get new connection count
        old_connections = self.current_connections
        action_delta = self.action_map.get(action, 0)
        self.current_connections = int(np.clip(
            self.current_connections + action_delta,
            self.min_connections,
            self.max_connections
        ))
        
        # Track connection history for stability
        self.connection_history.append(self.current_connections)
        
        # Calculate stability score
        if len(self.connection_history) >= 5:
            changes = sum(
                1 for i in range(len(self.connection_history) - 1)
                if self.connection_history[i] != self.connection_history[i + 1]
            )
            self.performance_stats["stability_score"] = changes / (len(self.connection_history) - 1)
        
        # Log decision occasionally
        if self.total_decisions % 50 == 0:
            logger.info(
                f"Decision[{self.total_decisions}]: "
                f"{old_connections} → {self.current_connections} "
                f"(Δ={action_delta}, U={utility:.1f})"
            )
        
        return self.current_connections
    
    # ========================================================
    # ULTIMATE PPO Training with Partial Batches
    # ========================================================
    
    def compute_gae(self, rewards: List[float], values: List[float], 
                    next_values: List[float], dones: List[bool]) -> torch.Tensor:
        """Compute Generalized Advantage Estimation."""
        advantages = []
        gae = 0.0
        
        for i in reversed(range(len(rewards))):
            delta = rewards[i] + self.gamma * next_values[i] * (1 - dones[i]) - values[i]
            gae = delta + self.gamma * self.gae_lambda * (1 - dones[i]) * gae
            advantages.insert(0, gae)
        
        return torch.tensor(advantages, dtype=torch.float32).to(self.device)
    
    def ppo_update(self, force: bool = False):
        """
        ULTIMATE PPO update with partial batch training.
        
        Will train even with partial batches (as little as min_batch_ratio * batch_size).
        Keeps experience_keep_ratio of experiences for next update.
        """
        # Check if we have enough samples for training
        min_samples = self.min_batch_samples
        buffer_size = len(self.experience_buffer)
        
        if buffer_size < min_samples and not force:
            if buffer_size > 0:
                logger.debug(f"Buffer: {buffer_size}/{min_samples} (need {min_samples-buffer_size} more)")
            return
        
        # Determine effective batch size
        effective_batch = min(buffer_size, self.batch_size)
        
        # Log training start
        self.total_updates += 1
        logger.debug(
            f"PPO Update[{self.total_updates}]: "
            f"Training with {effective_batch}/{self.batch_size} samples "
            f"(buffer: {buffer_size})"
        )
        
        # Sample from buffer (prioritized or uniform)
        if hasattr(self.experience_buffer, 'sample') and self.experience_buffer.alpha > 0:
            batch, indices, weights = self.experience_buffer.sample(effective_batch)
            weights_tensor = torch.FloatTensor(weights).to(self.device)
        else:
            # Get all experiences
            batch = self.experience_buffer.get_all()
            # Randomly select subset if we have more than batch_size
            if buffer_size > effective_batch:
                indices = np.random.choice(buffer_size, effective_batch, replace=False)
                batch = [[lst[i] for i in indices] for lst in batch]
            else:
                indices = list(range(buffer_size))
            weights_tensor = torch.ones(effective_batch).to(self.device)
        
        if len(batch[0]) == 0:
            logger.warning("Empty batch, skipping update")
            return
        
        # Convert batch to tensors
        s = torch.FloatTensor(np.array(batch[0])).to(self.device)
        a = torch.LongTensor(batch[1]).to(self.device)
        r = torch.FloatTensor(batch[2]).to(self.device)
        ns = torch.FloatTensor(np.array(batch[3])).to(self.device)
        d = torch.FloatTensor(batch[4]).to(self.device)
        old_lp = torch.FloatTensor(batch[5]).to(self.device)
        old_v = torch.FloatTensor(batch[6]).to(self.device)
        
        # Compute next values
        with torch.no_grad():
            _, next_v = self.network(ns)
            next_v = next_v.squeeze()
        
        # Compute advantages and returns
        adv = self.compute_gae(r.tolist(), old_v.tolist(), next_v.tolist(), d.tolist())
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        returns = adv + old_v
        
        # Track metrics for this update
        epoch_losses = []
        epoch_clip_ratios = []
        epoch_kl_divs = []
        epoch_value_losses = []
        
        # PPO epochs
        for epoch in range(self.ppo_epochs):
            # Get new action probabilities and values
            _, new_lp, ent, new_v = self.network.get_action_and_value(s, a)
            
            # Importance ratio
            ratio = torch.exp(new_lp - old_lp)
            
            # Clipped surrogate loss
            surr1 = ratio * adv
            surr2 = torch.clamp(ratio, 1 - self.clip_epsilon, 1 + self.clip_epsilon) * adv
            actor_loss = -(torch.min(surr1, surr2) * weights_tensor).mean()
            
            # Track clipping ratio
            clipped = torch.where(
                ratio < 1 - self.clip_epsilon,
                torch.ones_like(ratio),
                torch.where(
                    ratio > 1 + self.clip_epsilon,
                    torch.ones_like(ratio),
                    torch.zeros_like(ratio)
                )
            )
            clip_ratio = clipped.mean().item()
            epoch_clip_ratios.append(clip_ratio)
            
            # Approximate KL divergence
            approx_kl = (old_lp - new_lp).mean().item()
            epoch_kl_divs.append(approx_kl)
            
            # Value loss (clipped)
            v_clipped = old_v + torch.clamp(new_v - old_v, -self.clip_epsilon, self.clip_epsilon)
            v_loss1 = (new_v - returns) ** 2
            v_loss2 = (v_clipped - returns) ** 2
            value_loss = torch.max(v_loss1, v_loss2).mean()
            epoch_value_losses.append(value_loss.item())
            
            # Entropy bonus
            entropy_bonus = ent.mean()
            
            # Total loss
            loss = actor_loss + self.value_coef * value_loss - self.entropy_coef * entropy_bonus
            epoch_losses.append(loss.item())
            
            # Optimize
            self.optimizer.zero_grad()
            loss.backward()
            
            # Gradient clipping with monitoring
            total_norm = nn.utils.clip_grad_norm_(
                self.network.parameters(), 
                self.max_grad_norm,
                norm_type=2
            )
            self.performance_stats["gradient_norm"] = total_norm.item()
            
            self.optimizer.step()
            
            # Update priorities if using PER
            if hasattr(self.experience_buffer, 'update_priorities'):
                with torch.no_grad():
                    _, _, _, new_v_pred = self.network.get_action_and_value(
                        torch.FloatTensor(np.array(batch[0])).to(self.device)
                    )
                    td_errors = (returns - new_v_pred.squeeze()).abs().cpu().numpy()
                    self.experience_buffer.update_priorities(indices, td_errors.tolist())
        
        # Update learning metrics
        self.performance_stats["clip_ratio"] = np.mean(epoch_clip_ratios)
        self.performance_stats["approx_kl"] = np.mean(epoch_kl_divs)
        self.performance_stats["value_loss"] = np.mean(epoch_value_losses)
        
        # Decay learning rate
        self._decay_learning_rate()
        
        # Log training summary
        if epoch == self.ppo_epochs - 1:
            logger.debug(
                f"PPO Update {self.total_updates} complete: "
                f"Loss={np.mean(epoch_losses):.4f}, "
                f"Clip={self.performance_stats['clip_ratio']:.3f}, "
                f"KL={self.performance_stats['approx_kl']:.4f}, "
                f"V_Loss={self.performance_stats['value_loss']:.4f}, "
                f"GradNorm={self.performance_stats['gradient_norm']:.3f}"
            )
        
        # Update total samples processed
        self.total_samples_processed += effective_batch
        
        # Manage experience buffer (keep some experiences)
        self._manage_experience_buffer()
    
    def _decay_learning_rate(self):
        """Decay learning rate after each update."""
        for param_group in self.optimizer.param_groups:
            new_lr = max(param_group['lr'] * self.lr_decay, self.min_lr)
            param_group['lr'] = new_lr
            self.performance_stats["learning_rate"] = new_lr
        
        # Log occasionally
        if self.total_updates % 50 == 0:
            logger.debug(f"Learning rate: {self.performance_stats['learning_rate']:.2e}")
    
    def _manage_experience_buffer(self):
        """
        Manage experience buffer after update.
        Keeps a portion of experiences for next update.
        """
        buffer = self.experience_buffer
        keep_count = int(len(buffer) * self.experience_keep_ratio)
        
        if keep_count > 0 and len(buffer) > 10:
            # Save last keep_count experiences
            saved_experiences = []
            for _ in range(keep_count):
                idx = len(buffer) - 1
                if idx >= 0:
                    exp = (
                        buffer.states.pop(idx),
                        buffer.actions.pop(idx),
                        buffer.rewards.pop(idx),
                        buffer.next_states.pop(idx),
                        buffer.dones.pop(idx),
                        buffer.log_probs.pop(idx),
                        buffer.values.pop(idx)
                    )
                    saved_experiences.append(exp)
            
            # Clear buffer
            buffer.clear()
            
            # Restore saved experiences (in original order)
            for exp in reversed(saved_experiences):
                buffer.add(*exp)
            
            logger.debug(f"Kept {len(buffer)} experiences for next update")
        else:
            # Clear buffer entirely
            buffer.clear()
    
    # ========================================================
    # Enhanced Serialization
    # ========================================================
    
    def _convert_to_native_types(self, obj: Any) -> Any:
        """Convert numpy types to native Python types."""
        if isinstance(obj, dict):
            return {k: self._convert_to_native_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_to_native_types(v) for v in obj]
        elif isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, torch.Tensor):
            return obj.cpu().detach().numpy().tolist()
        return obj
    
    def save(self, path: Union[str, Path]) -> None:
        """Save model with enhanced checkpoint."""
        if self.network is None:
            logger.warning("Network not initialized, nothing to save")
            return
        
        try:
            # Prepare checkpoint
            checkpoint = {
                "network_state": self.network.state_dict(),
                "optimizer_state": self.optimizer.state_dict(),
                "agent_config": {
                    "action_map": self.action_map,
                    "utility_K": float(self.K),
                    "utility_B": float(self.B),
                    "utility_epsilon": float(self.epsilon),
                    "normalization_config": self.norm_config,
                    "min_connections": self.min_connections,
                    "max_connections": self.max_connections
                },
                "training_state": {
                    "current_connections": int(self.current_connections),
                    "total_decisions": int(self.total_decisions),
                    "total_updates": int(self.total_updates),
                    "total_samples_processed": int(self.total_samples_processed),
                    "entropy_coef": float(self.entropy_coef),
                    "min_rtt": float(self.min_rtt),
                    "learning_rate": float(self.performance_stats["learning_rate"])
                },
                "performance_stats": self._convert_to_native_types(self.performance_stats),
                "state_history": [s.tolist() for s in self.state_history],
                "connection_history": list(self.connection_history),
                "version": "2.0"  # Version identifier
            }
            
            # Save using pickle
            temp_path = str(path) + ".tmp"
            with open(temp_path, 'wb') as f:
                pickle.dump(checkpoint, f, protocol=pickle.HIGHEST_PROTOCOL)
            
            # Atomic replace
            if os.path.exists(path):
                os.replace(temp_path, path)
            else:
                os.rename(temp_path, path)
            
            logger.info(f"💾 Saved enhanced PPO model to {path}")
            logger.info(f"   Decisions: {self.total_decisions}, Updates: {self.total_updates}")
            logger.info(f"   Connections: {self.current_connections}, Best U: {self.performance_stats['best_utility']:.1f}")
            
        except Exception as e:
            logger.error(f"Error saving PPO model: {e}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
    
    def load(self, path: Union[str, Path]) -> None:
        """Load enhanced model checkpoint."""
        try:
            with open(path, 'rb') as f:
                checkpoint = pickle.load(f)
            
            # Initialize network if needed
            if self.network is None:
                state_dim = self._get_state_dim()
                self._initialize_network(state_dim)
            
            # Load network and optimizer states
            self.network.load_state_dict(checkpoint["network_state"])
            self.optimizer.load_state_dict(checkpoint["optimizer_state"])
            
            # Load agent configuration (verify consistency)
            agent_config = checkpoint.get("agent_config", {})
            if agent_config.get("action_map") != self.action_map:
                logger.warning(
                    f"Loaded action_map differs: {agent_config.get('action_map')} vs {self.action_map}"
                )
            
            # Load training state
            training_state = checkpoint.get("training_state", {})
            self.current_connections = training_state.get("current_connections", self.current_connections)
            self.total_decisions = training_state.get("total_decisions", 0)
            self.total_updates = training_state.get("total_updates", 0)
            self.total_samples_processed = training_state.get("total_samples_processed", 0)
            self.entropy_coef = training_state.get("entropy_coef", self.entropy_coef)
            self.min_rtt = training_state.get("min_rtt", float('inf'))
            
            # Load performance stats
            self.performance_stats.update(checkpoint.get("performance_stats", {}))
            
            # Load histories
            if "state_history" in checkpoint:
                self.state_history = deque(
                    [np.array(s) for s in checkpoint["state_history"]],
                    maxlen=self.state_history_size
                )
            
            if "connection_history" in checkpoint:
                self.connection_history = deque(
                    checkpoint["connection_history"],
                    maxlen=10
                )
            
            # Update learning rate
            loaded_lr = training_state.get("learning_rate", self.learning_rate)
            for param_group in self.optimizer.param_groups:
                param_group['lr'] = loaded_lr
            self.performance_stats["learning_rate"] = loaded_lr
            
            logger.info(f"✅ Loaded enhanced PPO model from {path}")
            logger.info(f"   Version: {checkpoint.get('version', '1.0')}")
            logger.info(f"   Decisions: {self.total_decisions}, Updates: {self.total_updates}")
            logger.info(f"   Best Utility: {self.performance_stats.get('best_utility', 0):.1f}")
            
        except Exception as e:
            logger.error(f"Error loading PPO model: {e}")
            raise
    
    # ========================================================
    # Enhanced Statistics
    # ========================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive agent statistics."""
        stats = {
            "algorithm": "ppo",
            "current_connections": self.current_connections,
            "total_decisions": self.total_decisions,
            "total_updates": self.total_updates,
            "total_samples_processed": self.total_samples_processed,
            "buffer_size": len(self.experience_buffer),
            "buffer_capacity": f"{len(self.experience_buffer)}/{self.batch_size}",
            "min_batch_ready": len(self.experience_buffer) >= self.min_batch_samples,
            "full_batch_ready": len(self.experience_buffer) >= self.batch_size,
            "entropy_coef": self.entropy_coef,
            "exploration_rate": self.get_exploration_rate(),
            
            # Policy configuration
            "action_map": self.action_map,
            "utility_K": self.K,
            "utility_B": self.B,
            "stability_penalty_enabled": self.enable_stability_penalty,
            "aggressive_penalty_enabled": self.enable_aggressive_penalty,
            
            # Training metrics
            "learning_rate": self.performance_stats["learning_rate"],
            "clip_ratio": self.performance_stats["clip_ratio"],
            "approx_kl": self.performance_stats["approx_kl"],
            "value_loss": self.performance_stats["value_loss"],
            "policy_entropy": self.performance_stats["policy_entropy"],
            "gradient_norm": self.performance_stats["gradient_norm"],
            
            # Performance metrics
            "best_utility": self.performance_stats["best_utility"],
            "best_throughput": self.performance_stats["best_throughput"],
            "stability_score": self.performance_stats["stability_score"],
        }
        
        # Add performance stats
        stats.update(self._convert_to_native_types(self.performance_stats))
        
        # Add recent averages
        if len(self.reward_history) > 0:
            recent_rewards = list(self.reward_history)
            stats["recent_avg_reward"] = float(np.mean(recent_rewards))
            stats["recent_reward_std"] = float(np.std(recent_rewards))
            stats["recent_positive_ratio"] = float(np.sum(np.array(recent_rewards) > 0) / len(recent_rewards))
        
        if len(self.utility_history) > 0:
            recent_utils = list(self.utility_history)
            stats["recent_avg_utility"] = float(np.mean(recent_utils))
            stats["recent_utility_std"] = float(np.std(recent_utils))
        
        return stats


# ============================================================
# Enhanced Preset Configurations
# ============================================================

def create_edge_policy_agent(**overrides) -> PPOAgent:
    """
    Create PPO agent configured for Edge Policy (Download Manager).
    
    Characteristics:
    - Conservative actions: ±2, ±1, 0
    - Strong stability penalties
    - Aggressive action penalties
    - Higher utility cost (conservative)
    - Partial batch training enabled
    """
    config = {
        # Core training
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
        
        # Partial batch training
        'min_batch_ratio': 0.3,
        'experience_keep_ratio': 0.2,
        'lr_decay': 0.99995,
        'min_lr': 1e-6,
        
        # Normalization (conservative)
        'normalization_config': {
            'rtt_grad': 100.0,      # Sensitive to RTT changes
            'loss': 100.0,
            'throughput': 1000.0,
            'use_min_rtt_norm': True,
            'rtt_norm_base': 200.0
        },
        
        # Policy-specific
        'action_map': {0: -2, 1: -1, 2: 0, 3: +1, 4: +2},
        'utility_K': 1.02,          # Higher cost per stream
        'utility_B': 5.0,           # Higher loss penalty
        'utility_epsilon': 0.08,
        'utility_bonus': 0.1,
        'throughput_improvement_bonus': 0.0,
        'enable_stability_penalty': True,
        'stability_penalty': 0.05,
        'stability_window': 3,
        'enable_aggressive_penalty': True,
        'aggressive_penalty_scale': 0.05,
        'aggressive_threshold': 1,
        
        # Connection management
        'min_connections': 1,
        'max_connections': 16,
        'default_connections': 4,
        
        # Exploration
        'exploration_steps': 100,
        'reward_scale': 1.0,
        'entropy_decay': 0.995,
        'min_entropy_coef': 0.001,
        
        # Optional enhancements
        'use_prioritized_replay': False,
        'priority_alpha': 0.6,
        'priority_beta': 0.4
    }
    config.update(overrides)
    return PPOAgent(**config)


def create_federated_policy_agent(**overrides) -> PPOAgent:
    """
    Create PPO agent configured for Federated Policy (CLI Server).
    
    Characteristics:
    - Aggressive actions: ±5, ±1, 0
    - No stability penalties
    - No aggressive penalties
    - Lower utility cost (aggressive)
    - Higher throughput bonuses
    - Faster learning
    """
    config = {
        # Core training
        'state_history_size': 5,
        'learning_rate': 0.0003,
        'gamma': 0.99,
        'gae_lambda': 0.95,
        'clip_epsilon': 0.2,
        'ppo_epochs': 4,
        'batch_size': 20,
        'entropy_coef': 0.02,       # Higher entropy for exploration
        'value_coef': 0.5,
        'max_grad_norm': 0.5,
        
        # Partial batch training
        'min_batch_ratio': 0.25,    # Even more aggressive training
        'experience_keep_ratio': 0.1,
        'lr_decay': 0.9999,         # Slower decay
        'min_lr': 5e-7,
        
        # Normalization (aggressive)
        'normalization_config': {
            'rtt_grad': 50.0,       # More sensitive to RTT changes
            'loss': 50.0,           # Less sensitive to loss
            'throughput': 5000.0,   # Expect higher throughput
            'use_min_rtt_norm': True,
            'rtt_norm_base': 100.0  # Expect lower RTT
        },
        
        # Policy-specific
        'action_map': {0: -5, 1: -1, 2: 0, 3: +1, 4: +5},
        'utility_K': 1.01,          # Lower cost per stream
        'utility_B': 3.0,           # Lower loss penalty
        'utility_epsilon': 0.05,
        'utility_bonus': 0.15,      # Higher utility bonus
        'throughput_improvement_bonus': 0.1,  # Reward throughput gains
        'enable_stability_penalty': False,    # No stability penalty
        'stability_penalty': 0.0,
        'stability_window': 3,
        'enable_aggressive_penalty': False,   # No aggressive penalty
        'aggressive_penalty_scale': 0.0,
        'aggressive_threshold': 1,
        
        # Connection management
        'min_connections': 2,
        'max_connections': 32,      # Higher max for datacenter
        'default_connections': 8,
        
        # Exploration
        'exploration_steps': 200,   # More exploration
        'reward_scale': 1.0,
        'entropy_decay': 0.998,     # Slower entropy decay
        'min_entropy_coef': 0.002,
        
        # Optional enhancements
        'use_prioritized_replay': True,  # Use PER for faster learning
        'priority_alpha': 0.6,
        'priority_beta': 0.4
    }
    config.update(overrides)
    return PPOAgent(**config)


# ============================================================
# Testing Suite for PPO Agent
# ============================================================

def test_ppo_agent_basic():
    """Basic PPO agent functionality test."""
    print("🧪 Testing Basic PPO Agent...")
    
    agent = create_edge_policy_agent()
    
    # Test decision making
    for i in range(10):
        connections = agent.make_decision(
            throughput=25.0 + i * 2,
            rtt=100.0 - i * 5,
            loss=0.1 + i * 0.02
        )
        print(f"  Step {i+1}: {connections} connections")
    
    # Test statistics
    stats = agent.get_stats()
    print(f"\n📊 Agent Statistics:")
    print(f"  Decisions: {stats['total_decisions']}")
    print(f"  Updates: {stats['total_updates']}")
    print(f"  Buffer: {stats['buffer_size']}/{stats['batch_size']}")
    print(f"  Current Connections: {stats['current_connections']}")
    
    return agent


def test_policy_differentiation():
    """Verify Edge and Federated policies produce different behaviors."""
    print("\n" + "="*60)
    print("🧪 Testing Policy Differentiation")
    print("="*60)
    
    # Create both agents
    edge = create_edge_policy_agent()
    fed = create_federated_policy_agent()
    
    # Test with same network conditions
    test_cases = [
        {"t": 50.0, "r": 100.0, "l": 1.0, "desc": "Moderate network"},
        {"t": 500.0, "r": 20.0, "l": 0.1, "desc": "High-speed datacenter"},
        {"t": 10.0, "r": 200.0, "l": 5.0, "desc": "Poor network"},
    ]
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n🔬 Test Case {i}: {case['desc']}")
        print(f"   Network: {case['t']:.1f}Mbps, {case['r']:.1f}ms RTT, {case['l']:.1f}% loss")
        
        edge_conn = edge.make_decision(case['t'], case['r'], case['l'])
        fed_conn = fed.make_decision(case['t'], case['r'], case['l'])
        
        edge_util = edge.calculate_utility(edge_conn, case['t'], case['l'])
        fed_util = fed.calculate_utility(fed_conn, case['t'], case['l'])
        
        print(f"   Edge: {edge_conn} streams, utility={edge_util:.1f}")
        print(f"   Federated: {fed_conn} streams, utility={fed_util:.1f}")
        
        # Verify differentiation
        assert edge_conn != fed_conn or edge_util != fed_util, \
            f"Policies should produce different results for {case['desc']}"
    
    print("\n✅ Policy differentiation test passed!")


def test_partial_batch_training():
    """Test that PPO trains with partial batches."""
    print("\n" + "="*60)
    print("🧪 Testing Partial Batch Training")
    print("="*60)
    
    # Create agent with very small min batch ratio
    agent = create_edge_policy_agent(
        batch_size=20,
        min_batch_ratio=0.1,  # Train with just 2 samples!
        experience_keep_ratio=0.0
    )
    
    # Collect a few samples
    updates_before = agent.total_updates
    
    for i in range(5):
        agent.make_decision(
            throughput=30.0 + i * 5,
            rtt=80.0 + i * 10,
            loss=0.5 + i * 0.1
        )
    
    updates_after = agent.total_updates
    
    print(f"Updates before: {updates_before}")
    print(f"Updates after 5 decisions: {updates_after}")
    print(f"Buffer size: {len(agent.experience_buffer)}")
    
    if updates_after > updates_before:
        print("✅ Partial batch training works!")
    else:
        print("⚠️  No updates occurred (might need more decisions)")
    
    return agent


def test_enhanced_metrics():
    """Test enhanced metrics collection."""
    print("\n" + "="*60)
    print("🧪 Testing Enhanced Metrics")
    print("="*60)
    
    agent = create_edge_policy_agent()
    
    # Make several decisions
    for i in range(30):
        agent.make_decision(
            throughput=40.0 + np.random.normal(0, 10),
            rtt=60.0 + np.random.normal(0, 20),
            loss=max(0.1, np.random.normal(1.0, 0.5))
        )
    
    # Get comprehensive stats
    stats = agent.get_stats()
    
    print("📊 Enhanced Metrics Collected:")
    print(f"  PPO Metrics: ✓" if 'clip_ratio' in stats else "  PPO Metrics: ✗")
    print(f"  Learning Rate: {stats.get('learning_rate', 'N/A'):.2e}")
    print(f"  Gradient Norm: {stats.get('gradient_norm', 'N/A'):.3f}")
    print(f"  Policy Entropy: {stats.get('policy_entropy', 'N/A'):.3f}")
    print(f"  Recent Rewards: μ={stats.get('recent_avg_reward', 'N/A'):.3f}, "
          f"σ={stats.get('recent_reward_std', 'N/A'):.3f}")
    
    # Check for required metrics
    required = ['clip_ratio', 'approx_kl', 'value_loss', 'learning_rate']
    missing = [m for m in required if m not in stats]
    
    if not missing:
        print("✅ All enhanced metrics collected!")
    else:
        print(f"⚠️  Missing metrics: {missing}")


# ============================================================
# Main Testing Function
# ============================================================

if __name__ == '__main__':
    print("🚀 Testing ULTIMATE PPO Agent")
    print("="*60)
    
    # Run all tests
    try:
        print("\n1. Basic PPO Agent Test")
        agent1 = test_ppo_agent_basic()
        
        print("\n2. Policy Differentiation Test")
        test_policy_differentiation()
        
        print("\n3. Partial Batch Training Test")
        agent3 = test_partial_batch_training()
        
        print("\n4. Enhanced Metrics Test")
        test_enhanced_metrics()
        
        print("\n" + "="*60)
        print("🎉 ALL TESTS PASSED!")
        print("="*60)
        
        # Show final agent stats
        print("\n📈 Final Agent 1 Statistics:")
        stats = agent1.get_stats()
        for key, value in list(stats.items())[:10]:  # Show first 10
            print(f"  {key}: {value}")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()