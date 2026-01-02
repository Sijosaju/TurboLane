"""
downloader.py - Multi-Stream Downloader with RL-based Optimization
Updated for corrected PPO implementation with proper episode handling.
"""
import os
import requests
import threading
from urllib.parse import urlparse, unquote
import time
import socket
import subprocess
import platform
import numpy as np
from config import *
from rl_manager import rl_manager


class MultiStreamDownloader:
    """
    Multi-stream downloader with reinforcement learning-based dynamic optimization.
    """
    
    def __init__(self, url, num_streams=DEFAULT_NUM_STREAMS, 
                 progress_callback=None, use_rl=False):
        """Initialize the downloader."""
        self.url = url
        self.num_streams = min(max(num_streams, MIN_STREAMS), MAX_STREAMS)
        self.progress_callback = progress_callback
        self.use_rl = use_rl
        
        # Download state
        self.file_size = 0
        self.downloaded_bytes = 0
        self.chunks = []
        self.temp_files = []
        self.is_downloading = False
        self.threads = []
        self.lock = threading.Lock()
        self.start_time = None
        
        # Enhanced metrics tracking for RL
        self.chunk_start_times = {}
        self.chunk_end_times = {}
        self.chunk_speeds = {}
        self.chunk_bytes = {}
        self.failed_chunks = set()
        self.active_chunks = set()
        
        # Network metrics (paper's state variables)
        self.network_metrics = {
            'throughput': 0.0,        # Mbps
            'rtt': 100.0,             # milliseconds
            'packet_loss': 0.1,       # percentage
            'last_update': time.time()
        }
        
        # Packet loss smoothing
        self.last_packet_loss = 0.1
        self.last_rtt = 100.0
        
        # Monitoring interval tracking
        self.last_mi_time = time.time()
        self.last_mi_bytes = 0
        
        # Episode tracking for RL
        self.episode_step = 0
        self.episode_reward = 0
        self.episode_ended = False
        
        # Dynamic control for RL mode
        if self.use_rl:
            self.current_stream_count = rl_manager.current_connections
            print("🤖 RL Mode: Reinforcement learning optimization enabled")
            print(f"   Initial streams: {self.current_stream_count}")
            
            # Safe access to exploration_rate - FIXED
            try:
                exploration_rate = rl_manager.performance_stats.get('exploration_rate', 1.0)
                print(f"   Exploration rate: {exploration_rate:.2f}")
            except (AttributeError, KeyError):
                print(f"   Exploration rate: 1.00 (default)")
        else:
            self.current_stream_count = self.num_streams
            print(f"📊 Static Mode: Using {self.num_streams} streams")

    # ==================== Network Metrics (Paper's State Variables) ====================
    
    def measure_rtt(self):
        """
        Measure actual network RTT using ping.
        Paper uses RTT as a key state variable (Section 3.1.1).
        """
        # Cache RTT for 2 seconds to avoid too frequent pings
        current_time = time.time()
        if hasattr(self, '_last_rtt_time') and current_time - self._last_rtt_time < 2.0:
            return self._last_rtt_value
        
        try:
            # Extract hostname from URL
            parsed_url = urlparse(self.url)
            hostname = parsed_url.hostname
            
            # Skip if no hostname
            if not hostname:
                return 100.0
            
            # Platform-specific ping command
            if platform.system().lower() == 'windows':
                param = '-n'
                timeout = '-w'
            else:
                param = '-c'
                timeout = '-W'
            
            command = ['ping', param, '1', timeout, '2000', hostname]
            
            result = subprocess.run(
                command, 
                capture_output=True, 
                text=True, 
                timeout=3
            )
            
            # Parse RTT from output
            output = result.stdout.lower()
            
            if 'time=' in output:
                # Linux/Mac format: time=10.123 ms
                line = [line for line in output.split('\n') if 'time=' in line]
                if line:
                    time_part = line[0].split('time=')[1].split()[0]
                    rtt = float(time_part.replace('ms', ''))
                    
                    # Cache the result
                    self._last_rtt_time = current_time
                    self._last_rtt_value = rtt
                    
                    return rtt
            
            elif 'average' in output:
                # Windows format
                lines = output.split('\n')
                for line in lines:
                    if 'average' in line and '=' in line:
                        parts = line.split('=')
                        if len(parts) >= 2:
                            rtt_str = parts[-1].strip()
                            rtt = float(rtt_str.split()[0].replace('ms', ''))
                            
                            # Cache the result
                            self._last_rtt_time = current_time
                            self._last_rtt_value = rtt
                            
                            return rtt
                            
        except subprocess.TimeoutExpired:
            if ENABLE_VERBOSE_LOGGING:
                print("⚠️  RTT measurement timeout")
        except Exception as e:
            if ENABLE_VERBOSE_LOGGING:
                print(f"⚠️  RTT measurement failed: {e}")
        
        # Fallback: estimate from chunk transfer times
        rtt = self.estimate_rtt_from_chunks()
        
        # Cache the fallback value
        self._last_rtt_time = current_time
        self._last_rtt_value = rtt
        
        return rtt
    
    def estimate_rtt_from_chunks(self):
        """
        Fallback RTT estimation from chunk patterns.
        Uses minimum chunk initiation delay as proxy.
        """
        if len(self.chunk_start_times) < 2:
            return 100.0  # Default
        
        # Use time between chunk initiations as rough proxy
        starts = sorted(self.chunk_start_times.values())
        if len(starts) >= 2:
            gaps = [starts[i+1] - starts[i] for i in range(len(starts)-1)]
            if gaps:
                min_gap = min(gaps)
                # Convert to milliseconds with reasonable bounds
                estimated_rtt = min(500, max(10, min_gap * 1000))
                return estimated_rtt
        
        return 100.0
    
    def estimate_packet_loss(self):
        """
        IMPROVED: More stable packet loss estimation.
        Uses chunk success rate and speed variance.
        """
        if not self.chunk_speeds:
            return self.last_packet_loss
        
        speeds = list(self.chunk_speeds.values())
        
        if len(speeds) < 2:
            return max(0.1, min(5.0, self.last_packet_loss))
        
        # Method 1: Normalized speed variance
        avg_speed = sum(speeds) / len(speeds)
        if avg_speed < 0.1:  # Avoid division by very small numbers
            variance_loss = 5.0  # High loss indication
        else:
            variance = sum((s - avg_speed) ** 2 for s in speeds) / len(speeds)
            std_dev = variance ** 0.5
            cv = std_dev / avg_speed  # Coefficient of variation
            variance_loss = min(5.0, cv * 10.0)  # 0-5% range
        
        # Method 2: Chunk failure rate
        total_chunks = len(self.chunks)
        if total_chunks == 0:
            failure_loss = 0.1
        else:
            failed_chunks = len(self.failed_chunks)
            failure_rate = failed_chunks / total_chunks
            failure_loss = min(10.0, failure_rate * 20.0)
        
        # Method 3: Active chunk rate (low active chunks might indicate issues)
        expected_active = min(self.current_stream_count, len(self.chunks))
        if expected_active > 0:
            active_rate = len(self.active_chunks) / expected_active
            activity_loss = (1.0 - active_rate) * 5.0
        else:
            activity_loss = 0.0
        
        # Weighted combination
        estimated_loss = (
            variance_loss * 0.4 + 
            failure_loss * 0.4 +
            activity_loss * 0.2
        )
        
        # Apply smoothing with previous value
        smoothing_factor = 0.8
        estimated_loss = (
            smoothing_factor * self.last_packet_loss + 
            (1 - smoothing_factor) * estimated_loss
        )
        
        # Realistic bounds: 0.1% to 10.0%
        estimated_loss = max(0.1, min(10.0, estimated_loss))
        
        self.last_packet_loss = estimated_loss
        
        return estimated_loss
    
    def calculate_throughput(self):
        """
        Calculate current throughput in Mbps.
        Paper's primary performance metric.
        """
        if not self.start_time or self.downloaded_bytes == 0:
            return 0.0
        
        elapsed = time.time() - self.start_time
        if elapsed < 0.1:
            return 0.0
        
        # Calculate throughput in Mbps
        bits_downloaded = self.downloaded_bytes * 8
        throughput_bps = bits_downloaded / elapsed
        throughput_mbps = throughput_bps / (1024 * 1024)
        
        return throughput_mbps
    
    def update_network_metrics(self):
        """
        Update all network metrics for RL state.
        Called at each monitoring interval.
        """
        current_time = time.time()
        
        # Calculate throughput
        throughput = self.calculate_throughput()
        
        # Measure RTT (with caching)
        rtt = self.measure_rtt()
        
        # Estimate packet loss
        packet_loss = self.estimate_packet_loss()
        
        # Store last values for gradient calculation
        old_rtt = self.last_rtt
        self.last_rtt = rtt
        
        # Update metrics
        self.network_metrics.update({
            'throughput': throughput,
            'rtt': rtt,
            'packet_loss': packet_loss,
            'rtt_gradient': (rtt - old_rtt) / max(0.1, RL_MONITORING_INTERVAL),
            'last_update': current_time
        })
        
        if LOG_NETWORK_METRICS and self.episode_step % NETWORK_METRICS_LOG_INTERVAL == 0:
            print(f"📈 Network Metrics [Step {self.episode_step}]: "
                  f"T={throughput:.2f}Mbps, RTT={rtt:.1f}ms, Loss={packet_loss:.2f}%")
        
        return throughput, rtt, packet_loss

    # ==================== RL Integration (Monitoring Intervals) ====================
    
    def should_run_mi(self):
        """
        Check if a Monitoring Interval (MI) should run.
        Paper's concept: periodic decision points (Section 3).
        """
        return time.time() - self.last_mi_time >= RL_MONITORING_INTERVAL
    
    def run_monitoring_interval(self):
        """
        Execute one monitoring interval cycle.
        
        This is the core of the paper's approach:
        1. Measure network state
        2. RL makes decision (adjust streams)
        3. RL learns from previous decision outcome
        """
        if not self.use_rl or self.episode_ended:
            return
        
        if not self.should_run_mi():
            return
        
        try:
            # Increment episode step
            self.episode_step += 1
            
            # Update network metrics (state variables)
            throughput, rtt, packet_loss = self.update_network_metrics()
            
            # RL learning from previous MI (done=False as episode continues)
            # Only learn if we've made at least one decision
            if self.episode_step > 1:
                rl_manager.learn_from_feedback(throughput, rtt, packet_loss, done=False)
            
            # RL makes new decision
            new_stream_count = rl_manager.make_decision(throughput, rtt, packet_loss)
            
            # Apply the decision
            if new_stream_count != self.current_stream_count:
                old_count = self.current_stream_count
                self.current_stream_count = new_stream_count
                print(f"🔄 Stream count adjusted: {old_count} → {new_stream_count} "
                      f"[Step {self.episode_step}]")
            
            # Reset MI timer
            self.last_mi_time = time.time()
            self.last_mi_bytes = self.downloaded_bytes
            
            # Log RL stats periodically
            if self.episode_step % 10 == 0:
                rl_stats = rl_manager.get_stats()
                print(f"📊 RL Stats: Avg Reward={rl_stats['average_reward']:.3f}, "
                      f"Updates={rl_stats['total_updates']}, "
                      f"Exploration={rl_stats['exploration_rate']:.2f}")
            
        except Exception as e:
            print(f"❌ MI execution error: {e}")
            import traceback
            traceback.print_exc()

    # ==================== Chunk Management ====================
    
    def get_filename_from_url(self):
        """Extract filename from URL."""
        path = urlparse(self.url).path
        filename = unquote(os.path.basename(path))
        return filename if filename else 'downloaded_file'
    
    def check_download_support(self):
        """Check if server supports range requests."""
        try:
            response = requests.head(
                self.url, 
                timeout=CONNECTION_TIMEOUT, 
                allow_redirects=True,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
            supports_ranges = response.headers.get('Accept-Ranges') == 'bytes'
            file_size = int(response.headers.get('Content-Length', 0))
            content_disposition = response.headers.get('Content-Disposition', '')
            
            filename = (
                content_disposition.split('filename=')[1].strip('"')
                if 'filename=' in content_disposition 
                else self.get_filename_from_url()
            )
            
            return supports_ranges, file_size, filename
            
        except Exception as e:
            print(f"⚠️  HEAD request failed, trying range request: {e}")
            try:
                headers = {
                    'Range': 'bytes=0-0',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = requests.get(
                    self.url, 
                    headers=headers, 
                    timeout=CONNECTION_TIMEOUT, 
                    stream=True
                )
                supports_ranges = response.status_code == 206
                
                if 'Content-Range' in response.headers:
                    file_size = int(response.headers['Content-Range'].split('/')[-1])
                else:
                    file_size = int(response.headers.get('Content-Length', 0))
                
                filename = self.get_filename_from_url()
                response.close()
                
                return supports_ranges, file_size, filename
                
            except Exception as e2:
                print(f"❌ Range request also failed: {e2}")
                return False, 0, self.get_filename_from_url()
    
    def calculate_chunks(self, file_size, max_streams):
        """
        Divide file into chunks for parallel download.
        Creates more chunks than initially needed for RL to scale up.
        """
        # Ensure minimum chunk size
        min_chunk_size = max(MIN_CHUNK_SIZE, 1024 * 1024)  # At least 1MB
        
        if file_size <= min_chunk_size:
            # File is too small for multiple chunks
            return [(0, file_size - 1)]
        
        # Determine number of chunks based on file size
        if file_size < min_chunk_size * max_streams:
            actual_chunks = max(1, file_size // min_chunk_size)
        else:
            actual_chunks = max_streams * 2  # Create extra chunks for RL flexibility
        
        chunk_size = file_size // actual_chunks
        
        chunks = []
        for i in range(actual_chunks):
            start = i * chunk_size
            if i == actual_chunks - 1:
                end = file_size - 1  # Last chunk gets remainder
            else:
                end = start + chunk_size - 1
            chunks.append((start, end))
        
        print(f"📊 Created {len(chunks)} chunks (size: {chunk_size/(1024*1024):.1f}MB each)")
        
        return chunks
    
    def download_chunk(self, chunk_id, start, end, temp_file):
        """
        Download a single chunk with error handling and metrics.
        """
        headers = {
            'Range': f'bytes={start}-{end}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Record start time
        with self.lock:
            self.chunk_start_times[chunk_id] = time.time()
            self.active_chunks.add(chunk_id)
        
        chunk_bytes = 0
        chunk_start = time.time()
        retries = 0
        max_retries = MAX_RETRIES
        
        while retries <= max_retries:
            try:
                with requests.get(
                    self.url,
                    headers=headers,
                    stream=True,
                    timeout=(CONNECTION_TIMEOUT, READ_TIMEOUT)
                ) as r:
                    if r.status_code not in [200, 206]:
                        print(f"❌ Chunk {chunk_id}: bad status {r.status_code}")
                        retries += 1
                        if retries <= max_retries:
                            time.sleep(RETRY_DELAY * retries)
                            continue
                        else:
                            raise Exception(f"Failed after {max_retries} retries")
                    
                    with open(temp_file, 'wb') as f:
                        for data in r.iter_content(chunk_size=BUFFER_SIZE):
                            if not self.is_downloading:
                                break
                            
                            f.write(data)
                            chunk_bytes += len(data)
                            
                            with self.lock:
                                self.downloaded_bytes += len(data)
                                if self.progress_callback:
                                    self.progress_callback(
                                        self.downloaded_bytes, 
                                        self.file_size
                                    )
                
                # Success - record metrics
                chunk_end = time.time()
                elapsed = chunk_end - chunk_start
                
                with self.lock:
                    self.chunk_end_times[chunk_id] = chunk_end
                    self.chunk_bytes[chunk_id] = chunk_bytes
                    if elapsed > 0:
                        self.chunk_speeds[chunk_id] = (chunk_bytes / (1024 * 1024)) / elapsed
                    else:
                        self.chunk_speeds[chunk_id] = 0
                    self.active_chunks.discard(chunk_id)
                
                if ENABLE_VERBOSE_LOGGING:
                    speed = (chunk_bytes / (1024 * 1024)) / max(elapsed, 0.1)
                    print(f"✅ Chunk {chunk_id} completed: {chunk_bytes/(1024*1024):.1f}MB "
                          f"in {elapsed:.1f}s ({speed:.1f} MB/s)")
                
                break  # Success, exit retry loop
                
            except Exception as e:
                retries += 1
                print(f"❌ Chunk {chunk_id} failed (attempt {retries}/{max_retries}): {e}")
                
                if retries <= max_retries:
                    # Wait before retry
                    time.sleep(RETRY_DELAY * retries)
                else:
                    # Final failure
                    with self.lock:
                        self.failed_chunks.add(chunk_id)
                        self.active_chunks.discard(chunk_id)
                    
                    # Remove partial file
                    if os.path.exists(temp_file):
                        try:
                            os.remove(temp_file)
                        except:
                            pass
                    
                    break
    
    def start_chunk_download(self, chunk_id, output_path):
        """Start downloading a specific chunk in a new thread."""
        if chunk_id >= len(self.chunks):
            return
        
        start, end = self.chunks[chunk_id]
        temp_file = f"{output_path}.part{chunk_id}"
        
        if temp_file not in self.temp_files:
            self.temp_files.append(temp_file)
        
        thread = threading.Thread(
            target=self.download_chunk,
            args=(chunk_id, start, end, temp_file),
            daemon=True
        )
        thread.start()
        self.threads.append(thread)
        
        if ENABLE_VERBOSE_LOGGING:
            print(f"📥 Started chunk {chunk_id}: bytes {start}-{end}")

    # ==================== Download Strategies ====================
    
    def download_with_rl(self, output_path):
        """
        RL-based adaptive multi-stream download.
        Implements the paper's dynamic stream adjustment approach.
        """
        print("🚀 Starting RL-based adaptive download...")
        
        self.is_downloading = True
        self.downloaded_bytes = 0
        self.start_time = time.time()
        self.last_mi_time = self.start_time
        self.threads, self.temp_files = [], []
        self.episode_step = 0
        self.episode_reward = 0
        self.episode_ended = False
        
        # Create chunks (more than initial streams for scaling)
        self.chunks = self.calculate_chunks(self.file_size, MAX_STREAMS)
        
        remaining = set(range(len(self.chunks)))
        
        # Start initial chunks based on RL's current decision
        initial_streams = min(self.current_stream_count, len(remaining))
        print(f"📊 Starting with {initial_streams} streams")
        
        for _ in range(initial_streams):
            if remaining:
                chunk_id = remaining.pop()
                self.start_chunk_download(chunk_id, output_path)
        
        # Main download loop with monitoring intervals
        last_progress_log = time.time()
        chunk_failures = 0
        consecutive_no_progress = 0
        last_downloaded_bytes = 0
        
        while (remaining or self.threads) and self.is_downloading:
            # Run monitoring interval (RL decision + learning)
            self.run_monitoring_interval()
            
            # Clean up completed threads
            self.threads = [t for t in self.threads if t.is_alive()]
            
            # Start new chunks if streams available
            active_threads = len(self.threads)
            available_slots = self.current_stream_count - active_threads
            
            if available_slots > 0 and remaining:
                chunks_to_start = min(available_slots, len(remaining))
                
                for _ in range(chunks_to_start):
                    if remaining:
                        chunk_id = remaining.pop()
                        self.start_chunk_download(chunk_id, output_path)
            
            # Check for failures
            current_failures = len(self.failed_chunks)
            if current_failures > chunk_failures:
                chunk_failures = current_failures
                print(f"⚠️  Chunk failure detected ({chunk_failures} total)")
            
            # Check for progress
            if self.downloaded_bytes == last_downloaded_bytes:
                consecutive_no_progress += 1
                if consecutive_no_progress > 5:
                    print("⚠️  No progress detected for 5 checks")
                    # Try to restart some chunks
                    if remaining and self.current_stream_count < len(self.chunks):
                        extra_streams = min(2, len(remaining))
                        for _ in range(extra_streams):
                            if remaining:
                                chunk_id = remaining.pop()
                                self.start_chunk_download(chunk_id, output_path)
            else:
                consecutive_no_progress = 0
                last_downloaded_bytes = self.downloaded_bytes
            
            # Progress logging (every 5 seconds)
            if time.time() - last_progress_log >= 5:
                if self.downloaded_bytes > 0 and self.file_size > 0:
                    progress = (self.downloaded_bytes / self.file_size) * 100
                    speed = self.calculate_throughput()
                    print(f"📊 Progress: {progress:.1f}% | "
                          f"Active: {len(self.active_chunks)}/{self.current_stream_count} | "
                          f"Speed: {speed:.1f} Mbps | "
                          f"Step: {self.episode_step}")
                last_progress_log = time.time()
            
            # Check timeout
            elapsed = time.time() - self.start_time
            if elapsed > NO_PROGRESS_TIMEOUT and self.downloaded_bytes == 0:
                print("❌ Download timeout - no progress")
                self.episode_ended = True
                break
            
            # Check max episode steps
            if self.episode_step > MAX_EPISODE_STEPS:
                print(f"⚠️  Max episode steps reached ({MAX_EPISODE_STEPS})")
                self.episode_ended = True
                break
            
            # Sleep to avoid busy waiting
            time.sleep(0.5)
        
        # Wait for all threads to complete
        timeout = 120  # 2 minutes max
        start_wait = time.time()
        while self.threads and time.time() - start_wait < timeout:
            self.threads = [t for t in self.threads if t.is_alive()]
            time.sleep(0.1)
        
        # Force terminate any remaining threads
        if self.threads:
            print(f"⚠️  {len(self.threads)} threads still active after timeout")
        
        success = len(self.failed_chunks) == 0 and self.downloaded_bytes == self.file_size
        
        # ✅ Signal episode end to RL agent
        if self.use_rl and not self.episode_ended:
            self.episode_ended = True
            
            # Get final metrics
            throughput, rtt, packet_loss = self.update_network_metrics()
            
            # Calculate final reward
            reward = self.calculate_reward_for_episode(success)
            
            # Learn with done=True
            print(f"📊 RL Episode complete. Steps: {self.episode_step}, "
                  f"Success: {success}, Final reward: {reward:.2f}")
            
            # Send final feedback
            rl_manager.learn_from_feedback(throughput, rtt, packet_loss, done=True)
            
            # Save RL model
            if MODEL_AUTO_SAVE:
                rl_manager.save_model()
        
        total_time = time.time() - self.start_time
        
        print(f"✅ Download {'completed' if success else 'finished'} in {total_time:.1f}s")
        print(f"   Success rate: {(len(self.chunks) - len(self.failed_chunks)) / len(self.chunks):.1%}")
        print(f"   Final throughput: {self.calculate_throughput():.1f} Mbps")
        print(f"   Total chunks: {len(self.chunks)}, Failed: {len(self.failed_chunks)}")
        
        return success
    
    def calculate_reward_for_episode(self, success):
        """Calculate final episode reward."""
        if success:
            # Base reward for success
            reward = REWARD_EPISODE_SUCCESS
            
            # Bonus for speed
            if self.file_size > 0 and self.start_time:
                elapsed = time.time() - self.start_time
                expected_time = self.file_size / (1024 * 1024) / 5  # Expected 5 MB/s
                if elapsed < expected_time:
                    speed_bonus = (expected_time - elapsed) / expected_time * REWARD_SPEED_BONUS_MAX
                    reward += speed_bonus
            
            # Bonus for efficient stream usage
            avg_streams = self.current_stream_count  # Simplified
            optimal_streams = 8  # Target for your network
            if avg_streams <= optimal_streams * 1.2:  # Within 20% of optimal
                reward += REWARD_EFFICIENCY_BONUS
        else:
            # Penalty for failure
            reward = REWARD_EPISODE_FAILURE
            
            # Additional penalty for many failures
            if len(self.failed_chunks) > len(self.chunks) * 0.5:  # >50% failure
                reward -= REWARD_EPISODE_FAILURE
        
        return reward
    
    def download_static(self, output_path):
        """
        Traditional static multi-stream download.
        Fixed number of streams throughout.
        """
        print(f"🚀 Starting static download with {self.num_streams} streams...")
        
        self.is_downloading = True
        self.downloaded_bytes = 0
        self.start_time = time.time()
        
        # Create chunks
        self.chunks = self.calculate_chunks(self.file_size, self.num_streams)
        
        # Start all chunks
        for i in range(len(self.chunks)):
            self.start_chunk_download(i, output_path)
        
        # Wait for completion
        start_wait = time.time()
        while self.threads and time.time() - start_wait < MAX_DOWNLOAD_TIME:
            self.threads = [t for t in self.threads if t.is_alive()]
            time.sleep(0.1)
        
        # Progress reporting
        if self.downloaded_bytes > 0 and self.file_size > 0:
            progress = (self.downloaded_bytes / self.file_size) * 100
            speed = self.calculate_throughput()
            print(f"📊 Final progress: {progress:.1f}% at {speed:.1f} Mbps")
        
        success = len(self.failed_chunks) == 0 and self.downloaded_bytes == self.file_size
        total_time = time.time() - self.start_time
        
        print(f"✅ Download {'completed' if success else 'finished'} in {total_time:.1f}s")
        
        return success

    # ==================== File Assembly ====================
    
    def assemble_file(self, output_file):
        """Assemble downloaded chunks into final file."""
        print(f"📦 Assembling {len(self.temp_files)} parts...")
        
        # Check for missing parts
        missing_parts = []
        for i, tmp in enumerate(self.temp_files):
            if not os.path.exists(tmp):
                missing_parts.append(i)
        
        if missing_parts:
            print(f"⚠️  Missing {len(missing_parts)} parts: {missing_parts}")
            return False
        
        try:
            with open(output_file, 'wb') as out:
                total_written = 0
                for i, tmp in enumerate(self.temp_files):
                    if os.path.exists(tmp):
                        file_size = os.path.getsize(tmp)
                        with open(tmp, 'rb') as part:
                            while True:
                                data = part.read(BUFFER_SIZE)
                                if not data:
                                    break
                                out.write(data)
                                total_written += len(data)
                        
                        # Remove temp file
                        try:
                            os.remove(tmp)
                        except:
                            pass
            
            # Verify file size
            if os.path.exists(output_file):
                actual_size = os.path.getsize(output_file)
                if actual_size == self.file_size:
                    print(f"✅ File assembled and verified: {actual_size/(1024*1024):.1f} MB")
                    return True
                else:
                    print(f"⚠️  Size mismatch: expected {self.file_size}, got {actual_size}")
                    return False
        
        except Exception as e:
            print(f"❌ File assembly error: {e}")
            return False
        
        return True
    
    def cleanup(self):
        """Clean up temporary files."""
        for f in self.temp_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass
    
    def cancel(self):
        """Cancel download."""
        print("🛑 Cancelling download...")
        self.is_downloading = False
        
        # Signal episode end for RL
        if self.use_rl and not self.episode_ended:
            self.episode_ended = True
            throughput, rtt, packet_loss = self.update_network_metrics()
            rl_manager.learn_from_feedback(throughput, rtt, packet_loss, done=True)
        
        time.sleep(1)
        self.cleanup()

    # ==================== Main Entry Point ====================
    
    def download(self, output_path=None):
        """
        Main download function.
        
        Returns:
            str: Path to downloaded file, or None if failed
        """
        try:
            print("🔍 Checking server support...")
            supports_ranges, file_size, filename = self.check_download_support()
            self.file_size = file_size
            
            if not supports_ranges:
                print("⚠️  Range requests not supported — using single stream")
                self.num_streams = 1
                self.use_rl = False
            
            output_path = output_path or os.path.join(DOWNLOAD_FOLDER, filename)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            print(f"💾 Output: {output_path}")
            print(f"📁 Size: {file_size / (1024*1024):.1f} MB")
            
            if file_size == 0:
                print("❌ File size is 0 or could not be determined")
                return None
            
            # Execute download strategy
            if self.use_rl:
                success = self.download_with_rl(output_path)
            else:
                success = self.download_static(output_path)
            
            if success and self.is_downloading:
                assembly_success = self.assemble_file(output_path)
                
                if assembly_success:
                    # Save RL state
                    if self.use_rl and LOG_EPISODE_SUMMARY:
                        rl_manager.print_stats()
                    
                    # Final metrics
                    final_throughput = self.calculate_throughput()
                    total_time = time.time() - self.start_time
                    print(f"📈 Final throughput: {final_throughput:.2f} Mbps")
                    print(f"⏱️  Total time: {total_time:.1f}s")
                    
                    return output_path
                else:
                    print("❌ File assembly failed")
            else:
                print("❌ Download failed or was cancelled")
            
            self.cleanup()
            return None
        
        except Exception as e:
            print(f"❌ Download error: {e}")
            import traceback
            traceback.print_exc()
            self.cleanup()
            return None
    
    def get_stats(self):
        """Get download statistics."""
        elapsed = time.time() - self.start_time if self.start_time else 0
        
        stats = {
            'elapsed_time': elapsed,
            'downloaded_bytes': self.downloaded_bytes,
            'file_size': self.file_size,
            'progress': (self.downloaded_bytes / self.file_size * 100) if self.file_size > 0 else 0,
            'throughput_mbps': self.calculate_throughput(),
            'num_chunks': len(self.chunks),
            'completed_chunks': len(self.chunk_end_times),
            'failed_chunks': len(self.failed_chunks),
            'active_chunks': len(self.active_chunks),
            'current_streams': self.current_stream_count,
            'use_rl': self.use_rl
        }
        
        if self.use_rl:
            stats['rl_stats'] = rl_manager.get_stats()
            stats['episode_step'] = self.episode_step
            stats['episode_ended'] = self.episode_ended
        
        return stats

    def get_detailed_metrics(self):
        """Get detailed download metrics for API."""
        stats = self.get_stats()
        
        # Add additional metrics
        detailed_stats = {
            **stats,
            'current_stream_count': self.current_stream_count,
            'use_rl': self.use_rl,
            'url': self.url,
            'is_downloading': self.is_downloading,
            'network_metrics': self.network_metrics.copy(),
            'chunk_progress': {
                'total': len(self.chunks),
                'completed': len(self.chunk_end_times),
                'failed': len(self.failed_chunks),
                'active': len(self.active_chunks)
            }
        }
        
        return detailed_stats