"""
turbolane/rl/agent.py - Q-Learning Agent for Multi-Stream Optimization

Balanced reward function for both Download Manager and DCI use cases.
"""

import json
import time
import random
from collections import deque


class RLAgent:
    """
    Q-Learning agent for optimizing parallel TCP stream count.
    Uses adaptive reward function that balances speed, efficiency, and stability.
    """

    def __init__(self,
                 learning_rate=0.1,
                 discount_factor=0.8,
                 exploration_rate=0.3,
                 min_exploration=0.05,
                 exploration_decay=0.995,
                 monitoring_interval=5.0,
                 min_connections=1,
                 max_connections=16,
                 default_connections=8):

        # RL parameters
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self.exploration_rate = exploration_rate
        self.min_exploration_rate = min_exploration
        self.exploration_decay = exploration_decay

        # Q-table
        self.Q = {}

        # Connection management
        self.current_connections = default_connections
        self.max_connections = max_connections
        self.min_connections = min_connections

        # Monitoring interval tracking
        self.last_decision_time = time.time()
        self.monitoring_interval = monitoring_interval

        # State tracking
        self.last_state = None
        self.last_action = None
        self.last_metrics = None

        # Performance tracking
        self.metrics_history = deque(maxlen=50)
        self.total_decisions = 0
        self.total_learning_updates = 0

        # Action history for pattern detection
        self.action_history = deque(maxlen=10)

        # Performance improvement tracking
        self.performance_stats = {
            'successful_adjustments': 0,
            'total_positive_rewards': 0,
            'total_negative_rewards': 0,
            'average_reward': 0,
            'total_reward': 0,
            'throughput_improvements': 0,
            'stream_efficiency': 0,
            'optimal_range_usage': 0
        }

    # ==================== State Representation ====================

    def discretize_state(self, throughput, rtt, packet_loss):
        """Discretize continuous state into discrete levels."""
        # Throughput levels (Mbps)
        if throughput < 10:
            throughput_level = 0
        elif throughput < 20:
            throughput_level = 1
        elif throughput < 30:
            throughput_level = 2
        elif throughput < 40:
            throughput_level = 3
        elif throughput < 50:
            throughput_level = 4
        else:
            throughput_level = 5

        # RTT levels (ms)
        if rtt < 30:
            rtt_level = 0
        elif rtt < 80:
            rtt_level = 1
        elif rtt < 150:
            rtt_level = 2
        else:
            rtt_level = 3

        # Packet loss levels (%)
        if packet_loss < 0.1:
            loss_level = 0
        elif packet_loss < 0.5:
            loss_level = 1
        elif packet_loss < 1.0:
            loss_level = 2
        elif packet_loss < 2.0:
            loss_level = 3
        else:
            loss_level = 4

        return (throughput_level, rtt_level, loss_level)

    # ==================== Action Selection ====================

    def get_available_actions(self):
        """Available actions for stream adjustment."""
        return {
            0: 2,   # Aggressive Increase (+2)
            1: 1,   # Conservative Increase (+1)
            2: 0,   # No Change
            3: -1,  # Conservative Decrease (-1)
            4: -2   # Aggressive Decrease (-2)
        }

    def get_q_value(self, state, action):
        """Get Q-value with neutral initialization."""
        if state not in self.Q:
            self.Q[state] = {a: 0.0 for a in range(5)}
        return self.Q[state].get(action, 0.0)

    def choose_action(self, state):
        """Epsilon-greedy action selection."""
        # Gradual exploration decay
        self.exploration_rate = max(
            self.min_exploration_rate,
            self.exploration_rate * self.exploration_decay
        )

        # Initialize new states with neutral values
        if state not in self.Q:
            self.Q[state] = {a: 0.0 for a in range(5)}

        # Enhanced exploration for new/underexplored states
        state_visits = len([m for m in self.metrics_history if m['state'] == state])
        if state_visits < 3:
            effective_exploration = min(0.5, self.exploration_rate * 2.0)
        else:
            effective_exploration = self.exploration_rate

        # Exploration
        if random.random() < effective_exploration:
            weights = [0.2, 0.2, 0.2, 0.2, 0.2]
            action = random.choices(range(5), weights=weights)[0]
            self.action_history.append(action)
            return action

        # Exploitation
        q_values = self.Q[state]
        max_q = max(q_values.values())
        best_actions = [a for a, q in q_values.items() if abs(q - max_q) < 0.001]

        # Oscillation prevention
        if len(self.action_history) >= 4:
            recent = list(self.action_history)[-4:]
            if (recent[0] in [0, 1] and recent[1] in [3, 4] and
                recent[2] in [0, 1] and recent[3] in [3, 4]):
                if 2 in best_actions:
                    action = 2
                else:
                    action = random.choice(best_actions)
            else:
                action = random.choice(best_actions)
        else:
            action = random.choice(best_actions)

        self.action_history.append(action)
        return action

    def apply_action_constraints(self, action, current_connections):
        """Apply action with intelligent constraints."""
        action_map = self.get_available_actions()
        change = action_map[action]
        new_connections = current_connections + change

        # Base bounds
        new_connections = max(self.min_connections,
                             min(self.max_connections, new_connections))

        # Intelligent constraints based on network conditions
        recent = list(self.metrics_history)[-3:] if len(self.metrics_history) >= 3 else []
        if recent:
            avg_throughput = sum(m['throughput'] for m in recent) / len(recent)
            avg_loss = sum(m['packet_loss'] for m in recent) / len(recent)
            avg_rtt = sum(m['rtt'] for m in recent) / len(recent)

            # Excellent conditions - encourage optimal range (6-12)
            if avg_throughput > 30 and avg_loss < 0.5 and avg_rtt < 100:
                if new_connections < 6 and change < 0:
                    return max(6, current_connections)
                elif new_connections > 12 and change > 0:
                    return min(12, new_connections)

            # Poor conditions - be conservative
            if avg_loss > 2.0 or avg_rtt > 200:
                if change > 0:
                    return min(current_connections + 1, new_connections)

        return new_connections

    # ==================== Reward Function ====================

    def calculate_reward(self, prev_throughput, curr_throughput,
                        prev_loss, curr_loss, num_streams):
        """
        Balanced reward for both DM and DCI: Speed + Efficiency + Stability
        """
        # 1. SPEED COMPONENT - Adaptive normalization
        # Use dynamic scaling based on observed max (not hardcoded)
        historical_max = max([m['throughput'] for m in self.metrics_history]) if self.metrics_history else curr_throughput
        speed_baseline = max(50.0, historical_max * 1.2)  # Adaptive ceiling
        speed_reward = (curr_throughput / speed_baseline) * 2.0  # Scale to ~0-2

        # 2. IMPROVEMENT COMPONENT - Reward positive changes
        delta_throughput = curr_throughput - prev_throughput
        improvement_reward = delta_throughput / 10.0  # MB/s improvement normalized

        # 3. EFFICIENCY COMPONENT - Penalize wasteful streams
        if num_streams > 0:
            throughput_per_stream = curr_throughput / num_streams
            # Penalize if efficiency drops below 5 MB/s per stream
            if throughput_per_stream < 5.0:
                efficiency_penalty = (5.0 - throughput_per_stream) * 0.3
            else:
                efficiency_penalty = 0.0
        else:
            efficiency_penalty = 0.0

        # 4. STREAM COUNT PENALTY - Progressive costs
        if num_streams <= 4:
            stream_penalty = 0.0
        elif num_streams <= 8:
            stream_penalty = (num_streams - 4) * 0.1
        elif num_streams <= 12:
            stream_penalty = 0.4 + (num_streams - 8) * 0.2
        else:
            stream_penalty = 1.2 + (num_streams - 12) * 0.4  # Steep penalty

        # 5. LOSS PENALTY - Quadratic for reliability
        loss_penalty = (curr_loss ** 2) * 0.5

        # 6. STABILITY BONUS - Reward maintaining good performance
        if abs(delta_throughput) < 5.0 and curr_throughput > 30.0 and curr_loss < 1.0:
            stability_bonus = 0.5
        else:
            stability_bonus = 0.0

        # FINAL REWARD
        reward = (speed_reward + improvement_reward + stability_bonus -
                 efficiency_penalty - stream_penalty - loss_penalty)

        # Bounded clipping for training stability
        reward = max(-5.0, min(5.0, reward))

        return reward

    # ==================== Q-Learning Update ====================

    def update_q_value(self, state, action, reward, next_state):
        """Q-learning update."""
        current_q = self.get_q_value(state, action)

        if next_state in self.Q:
            max_next_q = max(self.Q[next_state].values())
        else:
            max_next_q = 0.0

        # Q-learning update
        td_target = reward + self.discount_factor * max_next_q
        td_error = td_target - current_q

        # Adaptive learning rate
        if abs(reward) > 1.0:
            effective_lr = self.learning_rate * 1.5
        else:
            effective_lr = self.learning_rate

        new_q = current_q + effective_lr * td_error
        new_q = max(-10, min(10, new_q))

        if state not in self.Q:
            self.Q[state] = {a: 0.0 for a in range(5)}

        self.Q[state][action] = new_q
        self.total_learning_updates += 1

    # ==================== Decision Making ====================

    def should_make_decision(self):
        """Check if monitoring interval has passed."""
        return time.time() - self.last_decision_time >= self.monitoring_interval

    def make_decision(self, throughput, rtt, packet_loss_pct):
        """Main decision-making function."""
        if not self.should_make_decision():
            return self.current_connections

        self.total_decisions += 1

        try:
            current_state = self.discretize_state(throughput, rtt, packet_loss_pct)
            action = self.choose_action(current_state)
            new_connections = self.apply_action_constraints(action, self.current_connections)

            # Store for learning
            self.last_state = current_state
            self.last_action = action
            self.last_metrics = {
                'throughput': throughput,
                'rtt': rtt,
                'packet_loss': packet_loss_pct,
                'connections': self.current_connections
            }

            old_connections = self.current_connections
            self.current_connections = new_connections
            self.last_decision_time = time.time()

            if new_connections != old_connections:
                self.performance_stats['successful_adjustments'] += 1

            return self.current_connections

        except Exception as e:
            print(f"❌ RL Decision error: {e}")
            return self.current_connections

    def learn_from_feedback(self, current_throughput, current_rtt, current_packet_loss_pct):
        """Learn from feedback and update Q-table."""
        if self.last_state is None or self.last_action is None or self.last_metrics is None:
            self.last_metrics = {
                'throughput': current_throughput,
                'rtt': current_rtt,
                'packet_loss': current_packet_loss_pct,
                'connections': self.current_connections
            }
            return

        try:
            prev_throughput = self.last_metrics['throughput']
            prev_loss = self.last_metrics['packet_loss']

            reward = self.calculate_reward(
                prev_throughput, current_throughput,
                prev_loss, current_packet_loss_pct,
                self.current_connections
            )

            next_state = self.discretize_state(
                current_throughput, current_rtt, current_packet_loss_pct
            )

            self.update_q_value(self.last_state, self.last_action, reward, next_state)

            # ⚡ CRITICAL FIX: Track reward statistics
            self.performance_stats['total_reward'] += reward
            if reward > 0:
                self.performance_stats['total_positive_rewards'] += 1
            else:
                self.performance_stats['total_negative_rewards'] += 1

            if current_throughput > prev_throughput:
                self.performance_stats['throughput_improvements'] += 1

            # Update metrics history
            self.metrics_history.append({
                'state': self.last_state,
                'action': self.last_action,
                'reward': reward,
                'throughput': current_throughput,
                'rtt': current_rtt,
                'packet_loss': current_packet_loss_pct,
                'connections': self.current_connections,
                'timestamp': time.time()
            })

            # Update running averages
            if self.total_learning_updates > 0:
                self.performance_stats['average_reward'] = (
                    self.performance_stats['total_reward'] / self.total_learning_updates
                )

            if self.current_connections > 0:
                self.performance_stats['stream_efficiency'] = (
                    current_throughput / self.current_connections
                )

        except Exception as e:
            print(f"❌ RL Learning error: {e}")

    # ==================== Statistics ====================

    def get_stats(self):
        """Get comprehensive statistics."""
        total_updates = max(1, self.total_learning_updates)
        optimal_pct = (self.performance_stats['optimal_range_usage'] / total_updates * 100) if total_updates > 0 else 0

        return {
            'q_table_size': len(self.Q),
            'current_connections': self.current_connections,
            'exploration_rate': self.exploration_rate,
            'total_decisions': self.total_decisions,
            'total_learning_updates': self.total_learning_updates,
            'average_reward': self.performance_stats['average_reward'],
            'total_reward': self.performance_stats['total_reward'],
            'successful_adjustments': self.performance_stats['successful_adjustments'],
            'positive_rewards': self.performance_stats['total_positive_rewards'],
            'negative_rewards': self.performance_stats['total_negative_rewards'],
            'throughput_improvements': self.performance_stats['throughput_improvements'],
            'stream_efficiency': self.performance_stats['stream_efficiency'],
            'optimal_range_percentage': optimal_pct,
            'metrics_history_size': len(self.metrics_history),
            'monitoring_interval': self.monitoring_interval
        }
