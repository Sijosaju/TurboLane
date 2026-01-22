"""
rl_manager.py - Paper-Based Q-Learning with Safety Mechanisms
Designed to outperform fixed TCP connections while preventing congestion
Based on: "Learning to Maximize Network Bandwidth Utilization with Deep Reinforcement Learning"
"""

import json
import time
import random
import os
import numpy as np
from collections import deque
from config import *

class RLConnectionManager:
    """
    Q-Learning agent optimized for maximum throughput with safety constraints.
    Prevents congestion while learning optimal TCP stream allocation.
    """
    
    def __init__(self,
                 learning_rate=RL_LEARNING_RATE,
                 discount_factor=RL_DISCOUNT_FACTOR,
                 exploration_rate=RL_EXPLORATION_RATE):
        
        # RL parameters
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self.exploration_rate = exploration_rate
        self.min_exploration_rate = RL_MIN_EXPLORATION
        self.exploration_decay = RL_EXPLORATION_DECAY
        
        # Q-table
        self.Q = {}
        
        # Connection management
        self.current_connections = DEFAULT_NUM_STREAMS
        self.max_connections = MAX_STREAMS
        self.min_connections = MIN_STREAMS
        
        # State tracking with history
        self.state_history = deque(maxlen=STATE_HISTORY_LENGTH)
        self.last_state = None
        self.last_action = None
        self.last_metrics = None
        
        # Monitoring interval tracking
        self.last_decision_time = time.time()
        self.monitoring_interval = RL_MONITORING_INTERVAL
        
        # Performance tracking
        self.metrics_history = deque(maxlen=200)
        self.total_decisions = 0
        self.total_learning_updates = 0
        
        # Enhanced statistics
        self.performance_stats = {
            'total_reward': 0,
            'positive_rewards': 0,
            'negative_rewards': 0,
            'neutral_rewards': 0,
            'max_throughput_achieved': 0,
            'avg_throughput': 0,
            'avg_packet_loss': 0,
            'convergence_time': None,
            'episodes_completed': 0,
            'safety_interventions': 0,
            'emergency_interventions': 0
        }
        
        # Load existing Q-table
        self.load_q_table()
        
        if ENABLE_VERBOSE_LOGGING:
            print("\n" + "="*70)
            print("ðŸš€ RL MANAGER INITIALIZED - SAFE MODE")
            print("="*70)
            print(f"Learning Rate: {self.learning_rate}")
            print(f"Discount Factor: {self.discount_factor} (Î³=1.0 from paper)")
            print(f"Initial Exploration: {self.exploration_rate}")
            print(f"Stream Bounds: {MIN_STREAMS}-{MAX_STREAMS} (Safe: {SAFE_MAX_STREAMS})")
            print(f"Optimal Range: {OPTIMAL_MIN_STREAMS}-{OPTIMAL_MAX_STREAMS} streams")
            print(f"Utility K: {UTILITY_K}, B: {UTILITY_B}")
            print(f"Q-table size: {len(self.Q)} states")
            print(f"Safety: Congestion detection and emergency intervention ENABLED")
            print("="*70 + "\n")
    
    # ==================== Congestion Detection & Safety ====================
    
    def detect_congestion(self, packet_loss_pct, rtt):
        """
        Detect network congestion based on packet loss and RTT.
        Returns: (is_congested, severity_level)
        Severity: 0=healthy, 1=mild, 2=moderate, 3=severe
        """
        if packet_loss_pct >= SEVERE_CONGESTION_THRESHOLD or rtt > HIGH_RTT_THRESHOLD * 1.5:
            return True, 3  # Severe congestion
        elif packet_loss_pct >= CONGESTION_LOSS_THRESHOLD or rtt > HIGH_RTT_THRESHOLD:
            return True, 2  # Moderate congestion
        elif packet_loss_pct >= 0.5 or rtt > HIGH_RTT_THRESHOLD * 0.7:
            return True, 1  # Mild congestion
        else:
            return False, 0  # Healthy
    
    def apply_safety_constraints(self, new_connections, packet_loss_pct, rtt):
        """
        Apply intelligent safety constraints to prevent congestion.
        This is CRITICAL to prevent download failures.
        """
        original = new_connections
        
        # 1. Absolute hard limits
        new_connections = max(MIN_STREAMS, min(MAX_STREAMS, new_connections))
        
        # 2. Congestion-based constraints
        is_congested, severity = self.detect_congestion(packet_loss_pct, rtt)
        
        if is_congested:
            if severity == 3:  # Severe congestion - EMERGENCY
                # Drop to minimum safe level immediately
                new_connections = min(new_connections, 4)
                self.performance_stats['emergency_interventions'] += 1
                if LOG_SAFETY_INTERVENTIONS:
                    print(f"ðŸš¨ EMERGENCY: Severe congestion detected!")
                    print(f"   Loss={packet_loss_pct:.2f}%, RTT={rtt:.1f}ms")
                    print(f"   Forcing streams down to {new_connections}")
            
            elif severity == 2:  # Moderate congestion
                # Cap at current level, prevent increases
                new_connections = min(new_connections, self.current_connections)
                # If still high, reduce
                if new_connections > 10:
                    new_connections = min(10, new_connections)
                if LOG_SAFETY_INTERVENTIONS:
                    print(f"âš ï¸  SAFETY: Moderate congestion - capping at {new_connections}")
            
            elif severity == 1:  # Mild congestion
                # Limit increases
                if new_connections > self.current_connections:
                    new_connections = min(new_connections, self.current_connections + 1)
                if new_connections > SAFE_MAX_STREAMS:
                    new_connections = SAFE_MAX_STREAMS
        
        # 3. Historical performance constraints
        if len(self.metrics_history) >= 5:
            recent = list(self.metrics_history)[-5:]
            avg_loss = np.mean([m['packet_loss'] for m in recent])
            avg_throughput = np.mean([m['throughput'] for m in recent])
            
            # If recent performance is poor, be conservative
            if avg_loss > 1.0:  # Average loss > 1%
                new_connections = min(new_connections, 8)
                if LOG_SAFETY_INTERVENTIONS:
                    print(f"âš ï¸  SAFETY: High average loss ({avg_loss:.2f}%) - limiting to 8 streams")
            
            # If throughput is declining with more streams, back off
            if len(recent) >= 3:
                if recent[-1]['connections'] > recent[-3]['connections']:
                    if recent[-1]['throughput'] < recent[-3]['throughput'] * 0.9:
                        # More streams but worse throughput = congestion
                        new_connections = min(new_connections, recent[-3]['connections'])
                        if LOG_SAFETY_INTERVENTIONS:
                            print(f"âš ï¸  SAFETY: More streams causing worse throughput - backing off")
        
        # 4. Optimal range encouragement
        if not is_congested and packet_loss_pct < 0.5:
            # Good conditions - gently guide toward optimal range
            if new_connections < OPTIMAL_MIN_STREAMS:
                new_connections = max(new_connections, OPTIMAL_MIN_STREAMS)
            elif new_connections > OPTIMAL_MAX_STREAMS:
                # Don't force down, but discourage going higher
                if new_connections > SAFE_MAX_STREAMS:
                    new_connections = SAFE_MAX_STREAMS
        
        # 5. Log if safety intervened
        if new_connections != original:
            self.performance_stats['safety_interventions'] += 1
            if LOG_SAFETY_INTERVENTIONS:
                print(f"ðŸ›¡ï¸  SAFETY: Adjusted {original} â†’ {new_connections} streams")
        
        return new_connections
    
    # ==================== Enhanced State Representation ====================
    
    def calculate_rtt_gradient(self):
        """Calculate RTT gradient (change over time) - Paper Section III.A.1"""
        if len(self.metrics_history) < 2:
            return 0.0
        
        recent = list(self.metrics_history)[-2:]
        prev_rtt = recent[0]['rtt']
        curr_rtt = recent[1]['rtt']
        
        if prev_rtt == 0:
            return 0.0
        
        gradient = (curr_rtt - prev_rtt) / prev_rtt
        return np.clip(gradient, -1.0, 1.0)
    
    def calculate_rtt_ratio(self, current_rtt):
        """Calculate RTT ratio (current / minimum) - Paper Section III.A.1"""
        if not self.metrics_history:
            return 1.0
        
        min_rtt = min(m['rtt'] for m in self.metrics_history if m['rtt'] > 0)
        if min_rtt == 0:
            return 1.0
        
        ratio = current_rtt / min_rtt
        return np.clip(ratio, 1.0, 10.0)
    
    def discretize_value(self, value, bins):
        """Discretize continuous value into bins"""
        for i, threshold in enumerate(bins):
            if value < threshold:
                return i
        return len(bins)
    
    def discretize_state(self, throughput, rtt, packet_loss):
        """
        Enhanced state discretization with paper's recommended features.
        State includes: throughput level, RTT gradient, packet loss level, stream level
        """
        # Throughput discretization (7 bins)
        throughput_level = self.discretize_value(throughput, THROUGHPUT_BINS)
        
        # RTT gradient (5 bins) - More important than absolute RTT
        rtt_gradient = self.calculate_rtt_gradient()
        rtt_grad_level = self.discretize_value(rtt_gradient, RTT_GRADIENT_BINS)
        
        # Packet loss discretization (6 bins)
        loss_level = self.discretize_value(packet_loss, PACKET_LOSS_BINS)
        
        # Include current stream count as state feature
        if self.current_connections <= 5:
            stream_level = 0  # Low
        elif self.current_connections <= 15:
            stream_level = 1  # Medium
        elif self.current_connections <= 30:
            stream_level = 2  # High
        else:
            stream_level = 3  # Very high
        
        return (throughput_level, rtt_grad_level, loss_level, stream_level)
    
    # ==================== Paper's Utility Function (Equation 3) ====================
    
    def calculate_utility(self, throughput, packet_loss_pct, num_streams):
        """
        Paper's utility function: U(n, T, L) = T/(K*n) - T*L*B
        From Equation 3 in the research paper
        
        Components:
        - T/(K*n): Benefit term (throughput efficiency per stream)
        - T*L*B: Punishment term (throughput loss due to packet loss)
        """
        if num_streams == 0:
            return 0.0
        
        # Convert packet loss to decimal
        loss_decimal = packet_loss_pct / 100.0
        loss_decimal = np.clip(loss_decimal, 0.0, 1.0)
        
        # Paper's utility components
        benefit = throughput / (UTILITY_K * num_streams)
        punishment = throughput * loss_decimal * UTILITY_B
        
        utility = benefit - punishment
        
        return utility
    
    def calculate_enhanced_reward(self, prev_throughput, curr_throughput,
                                  prev_loss_pct, curr_loss_pct, num_streams):
        """
        Enhanced reward combining paper's utility with explicit throughput bonuses.
        
        Components:
        1. Utility difference (paper's approach)
        2. Logarithmic throughput bonus (prevents greediness)
        3. Throughput improvement bonus (encourages continuous gains)
        4. Severe congestion penalty (exponential packet loss punishment)
        """
        
        # Component 1: Paper's utility-based reward
        prev_utility = self.calculate_utility(prev_throughput, prev_loss_pct, num_streams)
        curr_utility = self.calculate_utility(curr_throughput, curr_loss_pct, num_streams)
        utility_diff = curr_utility - prev_utility
        
        # Component 2: Explicit throughput bonus (logarithmic)
        throughput_bonus = THROUGHPUT_BONUS_SCALE * np.log1p(curr_throughput)
        
        # Component 3: Throughput improvement bonus (delta reward)
        throughput_delta = curr_throughput - prev_throughput
        if throughput_delta > 0:
            improvement_bonus = IMPROVEMENT_BONUS_SCALE * np.log1p(throughput_delta)
        elif throughput_delta < 0:
            improvement_bonus = IMPROVEMENT_BONUS_SCALE * throughput_delta / max(prev_throughput, 1)
        else:
            improvement_bonus = 0.0
        
        # Component 4: Severe congestion penalty (exponential)
        loss_decimal = curr_loss_pct / 100.0
        if loss_decimal > 0.02:  # More than 2% loss indicates congestion
            congestion_penalty = -LOSS_PENALTY_MULTIPLIER * (loss_decimal ** 2)
        else:
            congestion_penalty = 0.0
        
        # Combine all components
        base_reward = 0.0
        
        # Utility-based threshold reward (paper's approach)
        if utility_diff > UTILITY_EPSILON:
            base_reward = REWARD_POSITIVE * min(3.0, 1.0 + abs(utility_diff) / 50.0)
            self.performance_stats['positive_rewards'] += 1
        elif utility_diff < -UTILITY_EPSILON:
            base_reward = REWARD_NEGATIVE * min(3.0, 1.0 + abs(utility_diff) / 50.0)
            self.performance_stats['negative_rewards'] += 1
        else:
            base_reward = REWARD_NEUTRAL
            self.performance_stats['neutral_rewards'] += 1
        
        # Total reward
        total_reward = (
            base_reward +           # Paper's utility-based reward
            throughput_bonus +      # Explicit throughput reward
            improvement_bonus +     # Continuous improvement incentive
            congestion_penalty      # Congestion avoidance
        )
        
        # Track statistics
        self.performance_stats['total_reward'] += total_reward
        
        if LOG_REWARD_DETAILS and abs(total_reward) > 5.0:
            print(f"\nðŸ’° REWARD BREAKDOWN:")
            print(f"   Base (utility): {base_reward:.2f}")
            print(f"   Throughput bonus: {throughput_bonus:.2f}")
            print(f"   Improvement bonus: {improvement_bonus:.2f}")
            print(f"   Congestion penalty: {congestion_penalty:.2f}")
            print(f"   TOTAL REWARD: {total_reward:.2f}")
            print(f"   Utility: {prev_utility:.1f} â†’ {curr_utility:.1f} (Î”={utility_diff:.1f})")
        
        return total_reward
    
    # ==================== Action Selection ====================
    
    def get_q_value(self, state, action):
        """Get Q-value with neutral initialization"""
        if state not in self.Q:
            self.Q[state] = {a: 0.0 for a in range(5)}
        return self.Q[state].get(action, 0.0)
    
    def choose_action(self, state):
        """
        Îµ-greedy action selection with decay.
        Paper uses PPO, but Îµ-greedy works well for Q-learning.
        """
        # Decay exploration rate
        self.exploration_rate = max(
            self.min_exploration_rate,
            self.exploration_rate * self.exploration_decay
        )
        
        # Initialize new states
        if state not in self.Q:
            self.Q[state] = {a: 0.0 for a in range(5)}
        
        # Exploration: try random actions
        if random.random() < self.exploration_rate:
            # Weighted toward moderate actions in early phase
            if self.total_decisions < 300:  # Early exploration
                weights = [0.25, 0.25, 0.25, 0.15, 0.10]  # Favor moderate increases
            else:
                weights = [0.2, 0.2, 0.2, 0.2, 0.2]  # Balanced
            
            action = random.choices(range(5), weights=weights)[0]
            return action
        
        # Exploitation: choose best action
        q_values = self.Q[state]
        max_q = max(q_values.values())
        
        # Get all actions with max Q-value (handle ties)
        best_actions = [a for a, q in q_values.items() if abs(q - max_q) < 0.001]
        action = random.choice(best_actions)
        
        return action
    
    def apply_action(self, action, packet_loss_pct, rtt):
        """
        Apply action with safety constraints.
        Takes packet_loss and rtt for safety checks.
        """
        change = ACTION_SPACE[action]
        new_connections = self.current_connections + change
        
        # Apply safety constraints
        new_connections = self.apply_safety_constraints(new_connections, packet_loss_pct, rtt)
        
        return new_connections
    
    # ==================== Q-Learning Update ====================
    
    def update_q_value(self, state, action, reward, next_state):
        """
        Standard Q-learning update: Q(s,a) â† Q(s,a) + Î±[r + Î³Â·max(Q(s',a')) - Q(s,a)]
        With Î³=1.0 as per paper's Table I
        """
        current_q = self.get_q_value(state, action)
        
        # Get max Q-value for next state
        if next_state in self.Q:
            max_next_q = max(self.Q[next_state].values())
        else:
            max_next_q = 0.0
        
        # Q-learning update
        td_target = reward + self.discount_factor * max_next_q
        td_error = td_target - current_q
        new_q = current_q + self.learning_rate * td_error
        
        # Update Q-table
        if state not in self.Q:
            self.Q[state] = {a: 0.0 for a in range(5)}
        self.Q[state][action] = new_q
        
        self.total_learning_updates += 1
        
        if LOG_Q_TABLE_UPDATES and abs(td_error) > 2.0:
            print(f"ðŸ“Š Q-Update: State={state}, Action={action}")
            print(f"   Q: {current_q:.2f} â†’ {new_q:.2f} (TD error: {td_error:.2f})")
        
        return new_q
    
    # ==================== Decision Making ====================
    
    def should_make_decision(self):
        """Check if monitoring interval has elapsed"""
        return time.time() - self.last_decision_time >= self.monitoring_interval
    
    def make_decision(self, throughput, rtt, packet_loss_pct):
        """
        Main decision-making function with safety mechanisms.
        Returns: optimal number of TCP streams
        """
        if not self.should_make_decision():
            return self.current_connections
        
        self.total_decisions += 1
        
        try:
            # SAFETY CHECK: Emergency intervention for severe congestion
            is_congested, severity = self.detect_congestion(packet_loss_pct, rtt)
            if severity == 3:  # Severe congestion
                # Override RL decision - emergency action
                emergency_streams = max(MIN_STREAMS, min(4, self.current_connections - 5))
                old_connections = self.current_connections
                self.current_connections = emergency_streams
                self.last_decision_time = time.time()
                self.performance_stats['emergency_interventions'] += 1
                
                if LOG_SAFETY_INTERVENTIONS:
                    print(f"\n{'='*70}")
                    print(f"ðŸš¨ EMERGENCY OVERRIDE - Severe Congestion Detected!")
                    print(f"{'='*70}")
                    print(f"Loss={packet_loss_pct:.2f}%, RTT={rtt:.1f}ms")
                    print(f"Streams: {old_connections} â†’ {self.current_connections} (EMERGENCY REDUCTION)")
                    print(f"{'='*70}\n")
                
                # Store metrics for learning (learn to avoid this!)
                self.last_metrics = {
                    'throughput': throughput,
                    'rtt': rtt,
                    'packet_loss': packet_loss_pct,
                    'connections': self.current_connections
                }
                
                return self.current_connections
            
            # Normal RL decision making
            current_state = self.discretize_state(throughput, rtt, packet_loss_pct)
            action = self.choose_action(current_state)
            
            # Apply action WITH safety constraints
            new_connections = self.apply_action(action, packet_loss_pct, rtt)
            
            # Store for learning
            self.last_state = current_state
            self.last_action = action
            self.last_metrics = {
                'throughput': throughput,
                'rtt': rtt,
                'packet_loss': packet_loss_pct,
                'connections': self.current_connections
            }
            
            # Update connection count
            old_connections = self.current_connections
            self.current_connections = new_connections
            self.last_decision_time = time.time()
            
            # Update statistics
            self.performance_stats['max_throughput_achieved'] = max(
                self.performance_stats['max_throughput_achieved'],
                throughput
            )
            
            # Logging
            if LOG_RL_DECISIONS:
                action_names = {
                    0: "INC(+3)", 1: "INC(+1)", 2: "STAY(0)",
                    3: "DEC(-1)", 4: "DEC(-3)"
                }
                
                # Congestion indicator
                congestion_status = "ðŸŸ¢ HEALTHY"
                if severity == 1:
                    congestion_status = "ðŸŸ¡ MILD CONGESTION"
                elif severity == 2:
                    congestion_status = "ðŸŸ  MODERATE CONGESTION"
                
                print(f"\n{'='*70}")
                print(f"ðŸ¤– RL DECISION #{self.total_decisions}")
                print(f"{'='*70}")
                print(f"Metrics: T={throughput:.1f} Mbps, RTT={rtt:.1f}ms, Loss={packet_loss_pct:.3f}%")
                print(f"Network: {congestion_status}")
                print(f"State: {current_state}")
                print(f"Action: {action_names[action]}")
                print(f"Streams: {old_connections} â†’ {new_connections}")
                print(f"Exploration: {self.exploration_rate:.4f}")
                print(f"Max Throughput: {self.performance_stats['max_throughput_achieved']:.1f} Mbps")
                
                # Safety range indicator
                if OPTIMAL_MIN_STREAMS <= new_connections <= OPTIMAL_MAX_STREAMS:
                    print(f"ðŸŽ¯ OPTIMAL RANGE")
                elif new_connections > SAFE_MAX_STREAMS:
                    print(f"âš ï¸  ABOVE SAFE RANGE")
                elif new_connections < OPTIMAL_MIN_STREAMS:
                    print(f"ðŸ“‰ BELOW OPTIMAL")
                
                print(f"{'='*70}\n")
            
            return self.current_connections
            
        except Exception as e:
            print(f"âŒ RL Decision error: {e}")
            import traceback
            traceback.print_exc()
            return self.current_connections
    
    def learn_from_feedback(self, current_throughput, current_rtt, current_packet_loss_pct):
        """
        Learning phase: update Q-values based on observed results.
        Called after each monitoring interval with new metrics.
        """
        if self.last_state is None or self.last_action is None or self.last_metrics is None:
            # First decision, initialize
            self.last_metrics = {
                'throughput': current_throughput,
                'rtt': current_rtt,
                'packet_loss': current_packet_loss_pct,
                'connections': self.current_connections
            }
            return
        
        try:
            # Get previous metrics
            prev_throughput = self.last_metrics['throughput']
            prev_loss = self.last_metrics['packet_loss']
            
            # Calculate reward
            reward = self.calculate_enhanced_reward(
                prev_throughput, current_throughput,
                prev_loss, current_packet_loss_pct,
                self.current_connections
            )
            
            # Create next state
            next_state = self.discretize_state(
                current_throughput, current_rtt, current_packet_loss_pct
            )
            
            # Q-learning update
            self.update_q_value(self.last_state, self.last_action, reward, next_state)
            
            # Store metrics in history
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
            if self.metrics_history:
                recent = list(self.metrics_history)[-20:]  # Last 20 measurements
                self.performance_stats['avg_throughput'] = np.mean([m['throughput'] for m in recent])
                self.performance_stats['avg_packet_loss'] = np.mean([m['packet_loss'] for m in recent])
            
            # Auto-save Q-table periodically
            if self.total_learning_updates % Q_TABLE_SAVE_INTERVAL == 0:
                self.save_q_table()
            
            if LOG_RL_DECISIONS:
                avg_reward = self.performance_stats['total_reward']/max(1, self.total_learning_updates)
                print(f"âœ… Learning update #{self.total_learning_updates}")
                print(f"   Reward: {reward:.2f}, Avg: {avg_reward:.2f}")
                print(f"   Safety interventions: {self.performance_stats['safety_interventions']}")
            
        except Exception as e:
            print(f"âŒ Learning error: {e}")
            import traceback
            traceback.print_exc()
    
    # ==================== Persistence ====================
    
    def save_q_table(self):
        """Save Q-table and statistics to disk"""
        try:
            q_table_serializable = {}
            for state, actions in self.Q.items():
                state_str = str(state)
                q_table_serializable[state_str] = actions
            
            data = {
                'q_table': q_table_serializable,
                'metadata': {
                    'total_states': len(self.Q),
                    'total_decisions': self.total_decisions,
                    'total_updates': self.total_learning_updates,
                    'exploration_rate': self.exploration_rate,
                    'performance_stats': self.performance_stats,
                    'timestamp': time.time()
                }
            }
            
            # Atomic write with backup
            temp_file = Q_TABLE_FILE + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            
            if os.path.exists(Q_TABLE_FILE):
                if os.path.exists(Q_TABLE_BACKUP):
                    os.remove(Q_TABLE_BACKUP)
                os.rename(Q_TABLE_FILE, Q_TABLE_BACKUP)
            os.rename(temp_file, Q_TABLE_FILE)
            
            if ENABLE_VERBOSE_LOGGING:
                print(f"ðŸ’¾ Q-table saved: {len(self.Q)} states")
                print(f"   Max throughput: {self.performance_stats['max_throughput_achieved']:.1f} Mbps")
                print(f"   Avg reward: {self.performance_stats['total_reward']/max(1,self.total_learning_updates):.2f}")
                print(f"   Safety interventions: {self.performance_stats['safety_interventions']}")
                print(f"   Emergency interventions: {self.performance_stats['emergency_interventions']}")
            
        except Exception as e:
            print(f"âŒ Error saving Q-table: {e}")
    
    def load_q_table(self):
        """Load Q-table and statistics from disk"""
        try:
            if os.path.exists(Q_TABLE_FILE):
                with open(Q_TABLE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                q_table_serializable = data.get('q_table', {})
                metadata = data.get('metadata', {})
                
                # Reconstruct Q-table
                self.Q = {}
                for state_str, actions in q_table_serializable.items():
                    try:
                        state = eval(state_str)
                        self.Q[state] = {int(k): v for k, v in actions.items()}
                    except:
                        continue
                
                # Load metadata
                self.total_decisions = metadata.get('total_decisions', 0)
                self.total_learning_updates = metadata.get('total_updates', 0)
                saved_exploration = metadata.get('exploration_rate', self.exploration_rate)
                self.exploration_rate = max(saved_exploration, self.min_exploration_rate)
                
                # Load performance stats
                if 'performance_stats' in metadata:
                    self.performance_stats.update(metadata['performance_stats'])
                
                print(f"âœ… Q-table loaded successfully")
                print(f"   States: {len(self.Q)}, Decisions: {self.total_decisions}")
                print(f"   Previous max throughput: {self.performance_stats.get('max_throughput_achieved', 0):.1f} Mbps")
                print(f"   Exploration rate: {self.exploration_rate:.4f}")
                print(f"   Safety interventions: {self.performance_stats.get('safety_interventions', 0)}")
                
        except Exception as e:
            print(f"âš ï¸  Could not load Q-table: {e}")
            print(f"   Starting fresh training...")
    
    # ==================== Statistics ====================
    
    def get_stats(self):
        """Get comprehensive statistics"""
        total_rewards = (
            self.performance_stats['positive_rewards'] +
            self.performance_stats['negative_rewards'] +
            self.performance_stats['neutral_rewards']
        )
        
        return {
            'q_table_size': len(self.Q),
            'current_connections': self.current_connections,
            'exploration_rate': self.exploration_rate,
            'total_decisions': self.total_decisions,
            'total_learning_updates': self.total_learning_updates,
            'avg_reward': self.performance_stats['total_reward'] / max(1, self.total_learning_updates),
            'positive_rewards': self.performance_stats['positive_rewards'],
            'negative_rewards': self.performance_stats['negative_rewards'],
            'neutral_rewards': self.performance_stats['neutral_rewards'],
            'max_throughput': self.performance_stats['max_throughput_achieved'],
            'avg_throughput': self.performance_stats['avg_throughput'],
            'avg_packet_loss': self.performance_stats['avg_packet_loss'],
            'success_rate': (self.performance_stats['positive_rewards'] / max(1, total_rewards)) * 100,
            'safety_interventions': self.performance_stats['safety_interventions'],
            'emergency_interventions': self.performance_stats['emergency_interventions']
        }
    
    def print_stats(self):
        """Print formatted statistics"""
        stats = self.get_stats()
        
        print("\n" + "="*70)
        print("ðŸ“Š RL MANAGER PERFORMANCE STATISTICS")
        print("="*70)
        print(f"Q-table States: {stats['q_table_size']}")
        print(f"Current Streams: {stats['current_connections']}")
        print(f"Total Decisions: {stats['total_decisions']}")
        print(f"Learning Updates: {stats['total_learning_updates']}")
        print(f"Exploration Rate: {stats['exploration_rate']:.4f}")
        print(f"\nReward Statistics:")
        print(f"  Average Reward: {stats['avg_reward']:.3f}")
        print(f"  Positive: {stats['positive_rewards']}, Negative: {stats['negative_rewards']}, Neutral: {stats['neutral_rewards']}")
        print(f"  Success Rate: {stats['success_rate']:.1f}%")
        print(f"\nThroughput Performance:")
        print(f"  Max Achieved: {stats['max_throughput']:.1f} Mbps")
        print(f"  Recent Average: {stats['avg_throughput']:.1f} Mbps")
        print(f"  Avg Packet Loss: {stats['avg_packet_loss']:.3f}%")
        print(f"\nSafety Mechanisms:")
        print(f"  Safety Interventions: {stats['safety_interventions']}")
        print(f"  Emergency Interventions: {stats['emergency_interventions']}")
        
        # Range assessment
        connections = stats['current_connections']
        if OPTIMAL_MIN_STREAMS <= connections <= OPTIMAL_MAX_STREAMS:
            range_status = "ðŸŽ¯ OPTIMAL"
        elif connections < OPTIMAL_MIN_STREAMS:
            range_status = "ðŸ“‰ BELOW OPTIMAL"
        elif connections <= SAFE_MAX_STREAMS:
            range_status = "ðŸ“Š SAFE RANGE"
        else:
            range_status = "âš ï¸ ABOVE SAFE"
        print(f"Current Range: {range_status}")
        
        print("="*70 + "\n")

# Global RL manager instance
rl_manager = RLConnectionManager()