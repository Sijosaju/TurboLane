"""
turbolane/rl/storage.py - Q-table persistence
"""
import json
import os
import time


class QTableStorage:
    """Handles Q-table loading and saving."""
    
    def __init__(self, storage_path='models/client', 
                 table_file='q_table.json',
                 backup_file='q_table_backup.json'):
        self.storage_path = storage_path
        self.table_file = os.path.join(storage_path, table_file)
        self.backup_file = os.path.join(storage_path, backup_file)
        
        # Ensure directory exists
        os.makedirs(storage_path, exist_ok=True)
    
    def load(self):
        """Load Q-table from disk."""
        try:
            if os.path.exists(self.table_file):
                with open(self.table_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                q_table_serializable = data.get('q_table', {})
                metadata = data.get('metadata', {})
                
                Q = {}
                for state_str, actions in q_table_serializable.items():
                    try:
                        state = eval(state_str)
                        Q[state] = {int(k): v for k, v in actions.items()}
                    except:
                        continue
                
                print(f"✅ Q-table loaded: {len(Q)} states")
                return Q, metadata
                
        except Exception as e:
            print(f"⚠️ Could not load Q-table: {e}")
        
        return {}, {}
    
    def save(self, Q, stats):
        """Save Q-table to disk."""
        try:
            q_table_serializable = {}
            for state, actions in Q.items():
                state_str = str(state)
                q_table_serializable[state_str] = actions
            
            data = {
                'q_table': q_table_serializable,
                'metadata': {
                    'total_states': len(Q),
                    'total_decisions': stats.get('total_decisions', 0),
                    'total_updates': stats.get('total_learning_updates', 0),
                    'exploration_rate': stats.get('exploration_rate', 0),
                    'average_reward': stats.get('average_reward', 0),
                    'throughput_improvements': stats.get('throughput_improvements', 0),
                    'optimal_range_usage': stats.get('optimal_range_usage', 0),
                    'timestamp': time.time()
                }
            }
            
            temp_file = self.table_file + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            
            if os.path.exists(self.table_file):
                os.replace(self.table_file, self.backup_file)
            
            os.replace(temp_file, self.table_file)
            
            print(f"💾 Q-table saved: {len(Q)} states")
            
        except Exception as e:
            print(f"❌ Error saving Q-table: {e}")