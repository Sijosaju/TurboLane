"""
rl_manager.py - Production PPO with PyTorch (Corrected)
Based on: "A Reinforcement Learning Approach to Optimize Available Network Bandwidth Utilization"

FIXED: Added exploration_rate to performance_stats
FIXED: Proper PPO implementation
"""

import json
import time
import random
import os
import numpy as np
from collections import deque
from config import *

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.distributions import Categorical
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    print("⚠️  PyTorch not available. Install with: pip install torch")


class ActorCriticNetwork(nn.Module):
    """
    Actor-Critic network for PPO.
    Actor: outputs action probabilities
    Critic: outputs state value estimate
    """
    
    def __init__(self, state_dim, action_dim, hidden_size=128):
        super(ActorCriticNetwork, self).__init__()
        
        # Shared feature extraction
        self.shared = nn.Sequential(
            nn.Linear(state_dim, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU()
        )
        
        # Actor head (policy)
        self.actor = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Linear(hidden_size // 2, action_dim)
        )
        
        # Critic head (value function)
        self.critic = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Linear(hidden_size // 2, 1)
        )
        
        # Initialize weights
        self.apply(self._init_weights)
    
    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            nn.init.orthogonal_(module.weight, gain=np.sqrt(2))
            nn.init.constant_(module.bias, 0.0)
    
    def forward(self, state):
        """Forward pass through network."""
        if not isinstance(state, torch.Tensor):
            state = torch.FloatTensor(state)
        
        # Handle batch and single state
        if len(state.shape) == 1:
            state = state.unsqueeze(0)
        
        features = self.shared(state)
        
        # Actor output (action logits)
        action_logits = self.actor(features)
        action_probs = torch.softmax(action_logits, dim=-1)
        
        # Critic output (state value)
        state_value = self.critic(features)
        
        return action_probs, state_value.squeeze()
    
    def get_action(self, state, deterministic=False):
        """Sample action from policy."""
        action_probs, state_value = self.forward(state)
        
        if deterministic:
            action = torch.argmax(action_probs, dim=-1)
            log_prob = torch.log(action_probs[0, action])
        else:
            # Create categorical distribution
            dist = Categorical(action_probs)
            action = dist.sample()
            log_prob = dist.log_prob(action)
        
        return action.item(), log_prob.item(), state_value.item()
    
    def evaluate_actions(self, states, actions):
        """Evaluate actions for PPO update."""
        action_probs, state_values = self.forward(states)
        dist = Categorical(action_probs)
        log_probs = dist.log_prob(actions)
        entropy = dist.entropy()
        
        return log_probs, state_values, entropy


class PPOConnectionManager:
    """
    PPO-based RL agent for optimizing parallel TCP streams.
    Correct implementation following the paper's Algorithm 1.
    """
    
    def __init__(self, 
                 learning_rate=3e-4,      # Standard learning rate for PPO
                 discount_factor=0.99,     # Standard discount factor
                 clip_param=0.2,          # PPO clipping parameter
                 ppo_epochs=10,           # Number of PPO epochs per update
                 batch_size=64,           # Minibatch size
                 entropy_coef=0.01,       # Entropy coefficient for exploration
                 value_coef=0.5,          # Value function coefficient
                 max_grad_norm=0.5):      # Gradient clipping
        
        if not TORCH_AVAILABLE:
            raise ImportError("PyTorch is required for PPO. Install with: pip install torch")
        
        # PPO hyperparameters (paper-tuned)
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self.clip_param = clip_param
        self.ppo_epochs = ppo_epochs
        self.batch_size = batch_size
        self.entropy_coef = entropy_coef
        self.value_coef = value_coef
        self.max_grad_norm = max_grad_norm
        
        # State space configuration
        self.history_length = PPO_HISTORY_LENGTH
        self.state_dim = 4 * self.history_length  # 4 metrics × history_length = 16
        self.action_dim = 5
        
        # Initialize network
        self.network = ActorCriticNetwork(self.state_dim, self.action_dim, hidden_size=PPO_HIDDEN_SIZE)
        self.optimizer = optim.Adam(self.network.parameters(), 
                                   lr=self.learning_rate,
                                   eps=1e-5)
        
        # Connection management
        self.current_connections = DEFAULT_NUM_STREAMS
        self.max_connections = MAX_STREAMS
        self.min_connections = MIN_STREAMS
        
        # Monitoring interval
        self.last_decision_time = time.time()
        self.monitoring_interval = RL_MONITORING_INTERVAL
        
        # State tracking
        self.state_history = deque(maxlen=self.history_length)
        self.min_rtt_observed = float('inf')
        
        # Experience buffer for PPO
        self.buffer = {
            'states': [],
            'actions': [],
            'log_probs': [],
            'rewards': [],
            'values': [],
            'dones': [],
            'advantages': [],
            'returns': []
        }
        
        # Episode tracking
        self.episode_rewards = []
        self.episode_lengths = []
        self.current_episode_reward = 0
        self.current_episode_length = 0
        
        # Metrics tracking
        self.last_metrics = None
        self.total_decisions = 0
        self.total_updates = 0
        
        # Performance stats - FIXED: Added exploration_rate
        self.performance_stats = {
            'total_reward': 0,
            'episode_rewards': [],
            'average_reward': 0,
            'successful_adjustments': 0,
            'throughput_improvements': 0,
            'avg_throughput': 0,
            'max_reward': -float('inf'),
            'min_reward': float('inf'),
            'recent_rewards': deque(maxlen=100),
            'action_distribution': np.zeros(self.action_dim),
            'exploration_rate': INITIAL_EXPLORATION,  # ✅ CRITICAL FIX
            'convergence_score': 0,
            'buffer_size': 0
        }
        
        # Exploration decay
        self.exploration_decay = (INITIAL_EXPLORATION - FINAL_EXPLORATION) / EXPLORATION_DECAY_STEPS
        
        # Load saved model if exists
        self.load_model()
        
        print("✅ PPO RL Manager initialized (Corrected PPO Implementation)")
        print(f"   State dim: {self.state_dim}, Action dim: {self.action_dim}")
        print(f"   Learning rate: {self.learning_rate}")
        print(f"   Exploration rate: {self.performance_stats['exploration_rate']:.2f}")
        print(f"   PPO epochs: {self.ppo_epochs}, Clip param: {self.clip_param}")
    
    # ==================== State Representation ====================
    
    def compute_state_vector(self, throughput, rtt, packet_loss_pct):
        """
        Compute normalized signal vector (Paper Section 3.1.1).
        Returns: [rtt_gradient, rtt_ratio, plr, throughput]
        """
        # Update minimum RTT
        self.min_rtt_observed = min(self.min_rtt_observed, rtt)
        
        # RTT ratio
        rtt_ratio = rtt / self.min_rtt_observed if self.min_rtt_observed > 0 else 1.0
        
        # RTT gradient
        if len(self.state_history) > 0:
            prev_rtt = self.state_history[-1][1]  # Previous RTT (unnormalized)
            rtt_gradient = (rtt - prev_rtt) / self.monitoring_interval
        else:
            rtt_gradient = 0.0
        
        # Normalize for stable learning
        rtt_gradient_norm = np.tanh(rtt_gradient / 10.0)
        rtt_ratio_norm = np.clip(rtt_ratio, 0, 2.0)
        plr_norm = np.clip(packet_loss_pct / 100.0, 0, 0.1)
        throughput_norm = throughput / 100.0  # Normalize to ~[0, 1]
        
        return np.array([rtt_gradient_norm, rtt_ratio_norm, plr_norm, throughput_norm], 
                       dtype=np.float32)
    
    def get_state(self, throughput, rtt, packet_loss_pct):
        """
        Get full state with history: s_t = (x_{t-n}, ..., x_t).
        """
        # Compute current signal vector
        signal_vector = self.compute_state_vector(throughput, rtt, packet_loss_pct)
        
        # Add to history (storing both normalized and raw RTT)
        self.state_history.append((signal_vector, rtt))
        
        # Build state from history (pad with zeros if needed)
        state = np.zeros(self.state_dim, dtype=np.float32)
        
        for i, (vec, _) in enumerate(self.state_history):
            start_idx = max(0, self.state_dim - (len(self.state_history) - i) * 4)
            end_idx = start_idx + 4
            state[start_idx:end_idx] = vec
        
        return state
    
    # ==================== Actions ====================
    
    def get_available_actions(self):
        """Action space (Paper Section 3.1.2)."""
        return {
            0: 5,    # Aggressive Increase
            1: 1,    # Conservative Increase
            2: 0,    # No Change
            3: -1,   # Conservative Decrease
            4: -5    # Aggressive Decrease
        }
    
    def apply_action(self, action):
        """Apply action with bounds checking."""
        action_map = self.get_available_actions()
        change = action_map[action]
        
        new_connections = self.current_connections + change
        new_connections = max(self.min_connections, 
                             min(self.max_connections, new_connections))
        
        return new_connections
    
    # ==================== Utility & Reward ====================
    
    def calculate_utility(self, throughput, packet_loss_pct, num_streams):
        """
        Utility function (Paper Equation 3):
        U(n_i, T_i, L_i) = (T_i / K^n_i) - (T_i * L_i * B)
        
        Based on config parameters.
        """
        # Import from config
        K = UTILITY_K
        B = UTILITY_B
        
        loss_decimal = packet_loss_pct / 100.0
        
        # Performance with diminishing returns
        performance_term = throughput / (K ** num_streams)
        
        # Packet loss punishment
        punishment_term = throughput * loss_decimal * B
        
        utility = performance_term - punishment_term
        
        if LOG_UTILITY_CALCULATIONS and self.total_decisions % 10 == 0:
            print(f"   🔧 Utility Debug: T={throughput:.1f}, streams={num_streams}, loss={packet_loss_pct:.2f}%")
            print(f"      Perf={performance_term:.2f}, Punishment={punishment_term:.2f}, U={utility:.2f}")
        
        return utility
    
    def calculate_reward(self, prev_throughput, curr_throughput,
                        prev_loss_pct, curr_loss_pct, num_streams):
        """
        Reward based on utility difference (Paper Section 3.1.3).
        """
        if self.last_metrics is None:
            return 0.0
        
        prev_utility = self.calculate_utility(
            prev_throughput, prev_loss_pct, 
            self.last_metrics['connections']
        )
        curr_utility = self.calculate_utility(
            curr_throughput, curr_loss_pct, num_streams
        )
        
        utility_diff = curr_utility - prev_utility
        
        # Threshold
        epsilon = UTILITY_EPSILON
        
        # Scaled reward
        if utility_diff > epsilon:
            reward = REWARD_POSITIVE * (1.0 + min(utility_diff / 10.0, 2.0))
            self.performance_stats['throughput_improvements'] += 1
        elif utility_diff < -epsilon:
            reward = REWARD_NEGATIVE * (1.0 + min(abs(utility_diff) / 10.0, 2.0))
        else:
            reward = 0.0
        
        # Update reward statistics
        self.performance_stats['total_reward'] += reward
        self.performance_stats['recent_rewards'].append(reward)
        self.performance_stats['max_reward'] = max(self.performance_stats['max_reward'], reward)
        self.performance_stats['min_reward'] = min(self.performance_stats['min_reward'], reward)
        
        if LOG_RL_DECISIONS:
            print(f"   💰 Reward: {reward:.2f} (ΔU: {utility_diff:.2f})")
        
        return reward
    
    # ==================== PPO Core Algorithms ====================
    
    def compute_gae(self, rewards, values, dones, next_value):
        """
        Compute Generalized Advantage Estimation (GAE).
        Correct implementation following Schulman et al.
        """
        gae = 0
        advantages = []
        
        for step in reversed(range(len(rewards))):
            if step == len(rewards) - 1:
                next_nonterminal = 1.0 - dones[step]
                next_value_est = next_value
            else:
                next_nonterminal = 1.0 - dones[step]
                next_value_est = values[step + 1]
            
            delta = (rewards[step] + 
                    self.discount_factor * next_value_est * next_nonterminal - 
                    values[step])
            gae = delta + self.discount_factor * PPO_GAE_LAMBDA * next_nonterminal * gae
            advantages.insert(0, gae)
        
        returns = [adv + val for adv, val in zip(advantages, values)]
        
        return torch.FloatTensor(advantages), torch.FloatTensor(returns)
    
    def update_buffer(self, state, action, log_prob, value, reward, done):
        """Add experience to buffer."""
        self.buffer['states'].append(state)
        self.buffer['actions'].append(action)
        self.buffer['log_probs'].append(log_prob)
        self.buffer['values'].append(value)
        self.buffer['rewards'].append(reward)
        self.buffer['dones'].append(done)
        
        # Update episode statistics
        self.current_episode_reward += reward
        self.current_episode_length += 1
        
        # Check if episode ended
        if done:
            self.episode_rewards.append(self.current_episode_reward)
            self.episode_lengths.append(self.current_episode_length)
            self.performance_stats['episode_rewards'].append(self.current_episode_reward)
            
            # Reset episode
            self.current_episode_reward = 0
            self.current_episode_length = 0
    
    def clear_buffer(self):
        """Clear the experience buffer."""
        for key in self.buffer:
            self.buffer[key] = []
    
    def prepare_training_data(self):
        """Prepare batch data for PPO training."""
        if len(self.buffer['states']) < MIN_BUFFER_SIZE:
            return None, None, None, None, None
        
        # Get next value for GAE
        with torch.no_grad():
            if len(self.buffer['states']) > 0:
                last_state = self.buffer['states'][-1]
                if isinstance(last_state, np.ndarray):
                    last_state = torch.FloatTensor(last_state).unsqueeze(0)
                _, next_value = self.network.forward(last_state)
                next_value = next_value.item()
            else:
                next_value = 0.0
        
        # Compute advantages and returns
        advantages, returns = self.compute_gae(
            self.buffer['rewards'],
            self.buffer['values'],
            self.buffer['dones'],
            next_value
        )
        
        # Normalize advantages
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        
        # Convert to tensors
        states = torch.FloatTensor(np.array(self.buffer['states']))
        actions = torch.LongTensor(self.buffer['actions'])
        old_log_probs = torch.FloatTensor(self.buffer['log_probs'])
        returns = returns
        advantages = advantages
        
        return states, actions, old_log_probs, returns, advantages
    
    def train_ppo(self):
        """
        Main PPO training loop.
        Follows Algorithm 1 from the paper with proper PPO implementation.
        """
        # Prepare training data
        states, actions, old_log_probs, returns, advantages = self.prepare_training_data()
        
        if states is None or len(states) < MIN_BUFFER_SIZE:
            return
        
        # PPO training epochs
        total_actor_loss = 0
        total_critic_loss = 0
        total_entropy = 0
        total_kl_div = 0
        
        for epoch in range(self.ppo_epochs):
            # Create random indices for minibatch
            indices = np.arange(len(states))
            np.random.shuffle(indices)
            
            # Minibatch updates
            for start in range(0, len(states), self.batch_size):
                end = start + self.batch_size
                batch_indices = indices[start:end]
                
                # Get minibatch
                batch_states = states[batch_indices]
                batch_actions = actions[batch_indices]
                batch_old_log_probs = old_log_probs[batch_indices]
                batch_returns = returns[batch_indices]
                batch_advantages = advantages[batch_indices]
                
                # Forward pass
                new_log_probs, state_values, entropy = self.network.evaluate_actions(
                    batch_states, batch_actions
                )
                
                # Ratio for clipping
                ratio = torch.exp(new_log_probs - batch_old_log_probs)
                
                # Clipped surrogate objective
                surr1 = ratio * batch_advantages
                surr2 = torch.clamp(ratio, 1.0 - self.clip_param, 1.0 + self.clip_param) * batch_advantages
                actor_loss = -torch.min(surr1, surr2).mean()
                
                # Value function loss with clipping
                value_pred_clipped = batch_returns + torch.clamp(
                    state_values - batch_returns, -self.clip_param, self.clip_param
                )
                value_losses = (state_values - batch_returns).pow(2)
                value_losses_clipped = (value_pred_clipped - batch_returns).pow(2)
                critic_loss = 0.5 * torch.max(value_losses, value_losses_clipped).mean()
                
                # Entropy bonus
                entropy_loss = -entropy.mean()
                
                # Total loss
                loss = actor_loss + self.value_coef * critic_loss + self.entropy_coef * entropy_loss
                
                # Calculate KL divergence for early stopping
                with torch.no_grad():
                    kl_div = (batch_old_log_probs - new_log_probs).mean().item()
                    total_kl_div += kl_div
                
                # Backpropagation
                self.optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.network.parameters(), self.max_grad_norm)
                self.optimizer.step()
                
                # Accumulate losses
                total_actor_loss += actor_loss.item()
                total_critic_loss += critic_loss.item()
                total_entropy += entropy.mean().item()
        
        # Update counters
        self.total_updates += 1
        
        # Update exploration rate (decay over time)
        decay_amount = min(self.exploration_decay * self.total_decisions, 
                          INITIAL_EXPLORATION - FINAL_EXPLORATION)
        self.performance_stats['exploration_rate'] = max(FINAL_EXPLORATION, 
                                                        INITIAL_EXPLORATION - decay_amount)
        
        # Update buffer size
        self.performance_stats['buffer_size'] = len(self.buffer['states'])
        
        # Log training statistics
        if LOG_PPO_TRAINING and self.total_updates % 5 == 0:
            avg_actor_loss = total_actor_loss / (self.ppo_epochs * np.ceil(len(states) / self.batch_size))
            avg_critic_loss = total_critic_loss / (self.ppo_epochs * np.ceil(len(states) / self.batch_size))
            avg_kl_div = total_kl_div / (self.ppo_epochs * np.ceil(len(states) / self.batch_size))
            
            print(f"   📊 PPO Update #{self.total_updates}")
            print(f"      Actor Loss: {avg_actor_loss:.4f}")
            print(f"      Critic Loss: {avg_critic_loss:.4f}")
            print(f"      Avg Entropy: {total_entropy/self.ppo_epochs:.4f}")
            print(f"      Avg KL Div: {avg_kl_div:.4f}")
            print(f"      Exploration: {self.performance_stats['exploration_rate']:.3f}")
            print(f"      Buffer Size: {len(states)}")
        
        # Clear buffer after training
        self.clear_buffer()
        
        # Save model periodically
        if self.total_updates % SAVE_FREQUENCY == 0:
            self.save_model()
    
    # ==================== Decision Making ====================
    
    def should_make_decision(self):
        """Check if monitoring interval has passed."""
        return time.time() - self.last_decision_time >= self.monitoring_interval
    
    def make_decision(self, throughput, rtt, packet_loss_pct):
        """Make decision using learned policy."""
        if not self.should_make_decision():
            return self.current_connections
        
        self.total_decisions += 1
        
        try:
            # Get state
            state = self.get_state(throughput, rtt, packet_loss_pct)
            
            # Choose action using policy (with exploration)
            deterministic = np.random.random() > self.performance_stats['exploration_rate']
            action, log_prob, value = self.network.get_action(state, deterministic=deterministic)
            
            # Update action distribution
            self.performance_stats['action_distribution'][action] += 1
            
            # Store for learning
            self.last_decision_state = state
            self.last_action = action
            self.last_log_prob = log_prob
            self.last_value = value
            
            # Apply action
            new_connections = self.apply_action(action)
            
            # Store metrics for reward calculation
            self.last_metrics = {
                'throughput': throughput,
                'rtt': rtt,
                'packet_loss': packet_loss_pct,
                'connections': self.current_connections,
                'state': state
            }
            
            # Update connection count
            old_connections = self.current_connections
            self.current_connections = new_connections
            self.last_decision_time = time.time()
            
            # Logging
            if LOG_RL_DECISIONS:
                action_names = {0: "AGGR_INC", 1: "INC", 2: "STAY", 3: "DEC", 4: "AGGR_DEC"}
                print(f"\n🤖 PPO Decision #{self.total_decisions}")
                print(f"   Metrics: T={throughput:.1f}Mbps, RTT={rtt:.1f}ms, Loss={packet_loss_pct:.2f}%")
                print(f"   Action: {action_names[action]} ({self.get_available_actions()[action]:+d})")
                print(f"   Streams: {old_connections} → {new_connections}")
                print(f"   Value Est: {value:.2f}, Exploration: {self.performance_stats['exploration_rate']:.2f}")
            
            if new_connections != old_connections:
                self.performance_stats['successful_adjustments'] += 1
            
            return self.current_connections
            
        except Exception as e:
            print(f"❌ PPO Decision error: {e}")
            import traceback
            traceback.print_exc()
            return self.current_connections
    
    def learn_from_feedback(self, current_throughput, current_rtt, current_packet_loss_pct, done=False):
        """Learn from feedback after action execution."""
        if self.last_metrics is None or not hasattr(self, 'last_action'):
            return
        
        try:
            # Calculate reward
            reward = self.calculate_reward(
                self.last_metrics['throughput'], current_throughput,
                self.last_metrics['packet_loss'], current_packet_loss_pct,
                self.current_connections
            )
            
            # Store experience in buffer
            self.update_buffer(
                state=self.last_metrics['state'],
                action=self.last_action,
                log_prob=self.last_log_prob,
                value=self.last_value,
                reward=reward,
                done=done
            )
            
            # Update performance stats
            self.performance_stats['avg_throughput'] = (
                (self.performance_stats['avg_throughput'] * 0.95 + 
                 current_throughput * 0.05)
            )
            
            # Update average reward
            if len(self.performance_stats['recent_rewards']) > 0:
                self.performance_stats['average_reward'] = np.mean(
                    list(self.performance_stats['recent_rewards'])
                )
            
            # Train if enough experience
            if len(self.buffer['states']) >= TARGET_BUFFER_SIZE:
                self.train_ppo()
            
            # If episode ended, force training
            if done and len(self.buffer['states']) > MIN_BUFFER_SIZE:
                self.train_ppo()
            
        except Exception as e:
            print(f"❌ PPO Learning error: {e}")
            import traceback
            traceback.print_exc()
    
    # ==================== Model Persistence ====================
    
    def save_model(self):
        """Save model weights and optimizer state."""
        try:
            model_path = Q_TABLE_FILE.replace('.json', '_ppo.pt')
            
            checkpoint = {
                'network_state_dict': self.network.state_dict(),
                'optimizer_state_dict': self.optimizer.state_dict(),
                'total_decisions': self.total_decisions,
                'total_updates': self.total_updates,
                'performance_stats': self.performance_stats,
                'min_rtt_observed': self.min_rtt_observed,
                'episode_rewards': self.episode_rewards,
                'episode_lengths': self.episode_lengths,
                'current_connections': self.current_connections
            }
            
            torch.save(checkpoint, model_path)
            
            if ENABLE_VERBOSE_LOGGING:
                avg_reward = self.performance_stats.get('average_reward', 0)
                print(f"💾 Model saved: {self.total_updates} updates, avg reward: {avg_reward:.2f}")
            
        except Exception as e:
            print(f"❌ Error saving model: {e}")
    
    def load_model(self):
        """Load model weights and optimizer state."""
        try:
            model_path = Q_TABLE_FILE.replace('.json', '_ppo.pt')
            
            if os.path.exists(model_path):
                checkpoint = torch.load(model_path)
                
                self.network.load_state_dict(checkpoint['network_state_dict'])
                self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
                self.total_decisions = checkpoint.get('total_decisions', 0)
                self.total_updates = checkpoint.get('total_updates', 0)
                self.performance_stats = checkpoint.get('performance_stats', self.performance_stats)
                self.min_rtt_observed = checkpoint.get('min_rtt_observed', float('inf'))
                self.episode_rewards = checkpoint.get('episode_rewards', [])
                self.episode_lengths = checkpoint.get('episode_lengths', [])
                self.current_connections = checkpoint.get('current_connections', DEFAULT_NUM_STREAMS)
                
                # Ensure exploration_rate exists
                if 'exploration_rate' not in self.performance_stats:
                    self.performance_stats['exploration_rate'] = INITIAL_EXPLORATION
                
                print(f"✅ Model loaded: {self.total_updates} updates, {self.total_decisions} decisions")
                print(f"   Previous performance: {self.performance_stats.get('average_reward', 0):.2f} avg reward")
                
        except Exception as e:
            print(f"⚠️  Could not load model: {e}")
    
    # ==================== Statistics ====================
    
    def get_stats(self):
        """Get comprehensive statistics."""
        # Normalize action distribution
        action_dist = self.performance_stats['action_distribution'].copy()
        if action_dist.sum() > 0:
            action_dist = action_dist / action_dist.sum()
        
        # Calculate convergence metrics
        convergence_score = 0
        if len(self.performance_stats['recent_rewards']) >= 10:
            recent_rewards = list(self.performance_stats['recent_rewards'])
            if np.mean(recent_rewards) != 0:
                convergence_score = 1.0 - (np.std(recent_rewards) / (np.abs(np.mean(recent_rewards)) + 1e-8))
        
        stats = {
            'current_connections': self.current_connections,
            'total_decisions': self.total_decisions,
            'total_updates': self.total_updates,
            'average_reward': self.performance_stats.get('average_reward', 0),
            'total_reward': self.performance_stats.get('total_reward', 0),
            'successful_adjustments': self.performance_stats.get('successful_adjustments', 0),
            'throughput_improvements': self.performance_stats.get('throughput_improvements', 0),
            'avg_throughput': self.performance_stats.get('avg_throughput', 0),
            'monitoring_interval': self.monitoring_interval,
            'exploration_rate': self.performance_stats.get('exploration_rate', 1.0),
            'min_rtt_observed': self.min_rtt_observed,
            'episode_count': len(self.episode_rewards),
            'avg_episode_reward': np.mean(self.episode_rewards) if self.episode_rewards else 0,
            'max_reward': self.performance_stats.get('max_reward', 0),
            'min_reward': self.performance_stats.get('min_reward', 0),
            'action_distribution': action_dist.tolist(),
            'convergence_score': convergence_score,
            'buffer_size': self.performance_stats.get('buffer_size', 0)
        }
        
        return stats
    
    def print_stats(self):
        """Print formatted statistics."""
        stats = self.get_stats()
        
        action_names = ["++5", "+1", "STAY", "-1", "--5"]
        action_dist = stats['action_distribution']
        
        print("\n" + "="*70)
        print("📊 PPO RL MANAGER STATISTICS (Corrected PPO)")
        print("="*70)
        print(f"Current Streams:         {stats['current_connections']}")
        print(f"Total Decisions:         {stats['total_decisions']}")
        print(f"PPO Updates:             {stats['total_updates']}")
        print(f"Average Reward:          {stats['average_reward']:.3f}")
        print(f"Convergence Score:       {stats['convergence_score']:.2f}")
        print(f"Exploration Rate:        {stats['exploration_rate']:.3f}")
        print(f"Episode Count:           {stats['episode_count']}")
        print(f"Avg Episode Reward:      {stats['avg_episode_reward']:.2f}")
        print(f"Buffer Size:             {stats['buffer_size']}")
        print("\nAction Distribution:")
        for name, prob in zip(action_names, action_dist):
            print(f"  {name}: {prob:.2%}")
        print("="*70 + "\n")
    
    # ==================== Diagnostic Tools ====================
    
    def diagnose(self):
        """Run diagnostic checks on the PPO agent."""
        print("\n🔍 PPO Agent Diagnostic")
        print("="*50)
        
        # Check network architecture
        total_params = sum(p.numel() for p in self.network.parameters())
        print(f"Network Parameters: {total_params:,}")
        
        # Check buffer
        print(f"Buffer Size: {len(self.buffer['states'])}")
        
        # Check gradient flow
        for name, param in self.network.named_parameters():
            if param.grad is not None:
                grad_mean = param.grad.abs().mean().item()
                print(f"  {name}: grad={grad_mean:.6f}")
        
        # Check utility function
        test_cases = [
            (35, 1.5, 8),   # Optimal
            (35, 5.0, 15),  # Too many streams with high loss
            (20, 0.5, 3),   # Too few streams
        ]
        
        print("\nUtility Function Test:")
        for throughput, loss, streams in test_cases:
            utility = self.calculate_utility(throughput, loss, streams)
            print(f"  T={throughput}, L={loss}%, S={streams} -> U={utility:.2f}")
        
        print("="*50)


# Global PPO manager instance
rl_manager = PPOConnectionManager()