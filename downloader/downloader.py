
"""
downloader.py - Multi-Stream Downloader with RL-based Optimization
Fixed version with better metrics and stable RL behavior
"""
import os
import requests
import threading
from urllib.parse import urlparse, unquote
import time
import socket
import subprocess
import platform
from downloader.config import *
from turbolane.engine import TurboLaneEngine

turbolane_controller = TurboLaneEngine(mode='client')
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
        if self.use_rl:
            self.turbolane = turbolane_controller
            self.current_stream_count = self.turbolane.policy.agent.current_connections
        
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
        
        # Monitoring interval tracking
        self.last_mi_time = time.time()
        self.last_mi_bytes = 0
        
        # Dynamic control for RL mode
        if self.use_rl:
            self.current_stream_count = self.turbolane.policy.agent.current_connections
            print("🤖 RL Mode: Reinforcement learning optimization enabled")
            print(f"   Initial streams: {self.current_stream_count}")
        else:
            self.current_stream_count = self.num_streams
            print(f"📊 Static Mode: Using {self.num_streams} streams")

    # ==================== Network Metrics (Paper's State Variables) ====================
    
    def measure_rtt(self):
        """
        Measure actual network RTT using ping.
        Paper uses RTT as a key state variable (Section 3.1.1).
        """
        try:
            # Extract hostname from URL
            hostname = urlparse(self.url).hostname
            
            # Platform-specific ping command
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            command = ['ping', param, '1', '-W', '2', hostname]
            
            result = subprocess.run(
                command, 
                capture_output=True, 
                text=True, 
                timeout=3
            )
            
            # Parse RTT from output
            output = result.stdout.lower()
            
            # Different platforms have different output formats
            if 'time=' in output:
                # Linux/Mac format: time=X.XXX ms
                rtt_str = output.split('time=')[1].split()[0]
                rtt = float(rtt_str.replace('ms', ''))
                return rtt
            elif 'average' in output:
                # Windows format may have average
                parts = output.split('=')
                if len(parts) >= 2:
                    rtt = float(parts[-1].replace('ms', '').strip())
                    return rtt
                    
        except Exception as e:
            if ENABLE_VERBOSE_LOGGING:
                print(f"⚠️  RTT measurement failed: {e}")
        
        # Fallback: estimate from chunk transfer times
        return self.estimate_rtt_from_chunks()
    
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
            min_gap = min(gaps) if gaps else 0.1
            # Convert to milliseconds with reasonable bounds
            estimated_rtt = min(1000, max(10, min_gap * 1000))
            return estimated_rtt
        
        return 100.0
    
    def estimate_packet_loss(self):
        """
        IMPROVED: More stable packet loss estimation.
        """
        if not self.chunk_speeds:
            return 0.1  # Default: 0.1% (excellent)
        
        speeds = list(self.chunk_speeds.values())
        
        if len(speeds) < 3:
            return 0.1
        
        # Use only recent chunks for more responsive but stable estimation
        recent_speeds = speeds[-5:] if len(speeds) >= 5 else speeds
        
        # Method 1: Normalized speed variance
        avg_speed = sum(recent_speeds) / len(recent_speeds)
        if avg_speed < 0.1:  # Avoid division by very small numbers
            return 1.0
        
        variance = sum((s - avg_speed) ** 2 for s in recent_speeds) / len(recent_speeds)
        std_dev = variance ** 0.5
        cv = std_dev / avg_speed  # Coefficient of variation
        
        # Method 2: Chunk failure rate (weighted more heavily)
        total_chunks = len(self.chunks)
        failed_chunks = len(self.failed_chunks)
        failure_rate = failed_chunks / total_chunks if total_chunks > 0 else 0
        
        # Conservative combination
        # CV: 0.0-0.5 -> 0.1-1.0% loss
        loss_from_variance = min(1.0, cv * 2.0)
        
        # Failures: more significant indicator
        loss_from_failures = min(3.0, failure_rate * 15.0)
        
        # Weighted combination (failures are more important)
        estimated_loss = (
            loss_from_variance * 0.3 + 
            loss_from_failures * 0.7
        )
        
        # Apply smoothing with previous value
        smoothing_factor = 0.7
        estimated_loss = (smoothing_factor * self.last_packet_loss + 
                         (1 - smoothing_factor) * estimated_loss)
        
        self.last_packet_loss = estimated_loss
        
        # Realistic bounds: 0.1% to 5.0%
        return max(0.1, min(5.0, estimated_loss))
    
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
        
        # Measure RTT
        rtt = self.measure_rtt()
        
        # Estimate packet loss
        packet_loss = self.estimate_packet_loss()
        
        # Update metrics
        self.network_metrics.update({
            'throughput': throughput,
            'rtt': rtt,
            'packet_loss': packet_loss,
            'last_update': current_time
        })
        
        if LOG_NETWORK_METRICS:
            print(f"📈 Network Metrics: T={throughput:.2f}Mbps, RTT={rtt:.1f}ms, Loss={packet_loss:.2f}%")
        
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
        if not self.use_rl:
            return
        
        if not self.should_run_mi():
            return
        
        try:
            # Update network metrics (state variables)
            throughput, rtt, packet_loss = self.update_network_metrics()
            
            # RL learning from previous MI
            self.turbolane.learn(throughput, rtt, packet_loss)
            new_stream_count = self.turbolane.decide(throughput, rtt, packet_loss)
            
            # Apply the decision
            if new_stream_count != self.current_stream_count:
                old_count = self.current_stream_count
                self.current_stream_count = new_stream_count
                print(f"🔄 Stream count adjusted: {old_count} → {new_stream_count}")
            
            # Reset MI timer
            self.last_mi_time = time.time()
            self.last_mi_bytes = self.downloaded_bytes
            
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
                allow_redirects=True
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
                headers = {'Range': 'bytes=0-0'}
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
        
        # Determine number of chunks based on file size
        if file_size < min_chunk_size * max_streams:
            actual_chunks = max(1, file_size // min_chunk_size)
        else:
            actual_chunks = max_streams
        
        chunk_size = file_size // actual_chunks
        
        chunks = []
        for i in range(actual_chunks):
            start = i * chunk_size
            end = file_size - 1 if i == actual_chunks - 1 else (i + 1) * chunk_size - 1
            chunks.append((start, end))
        
        print(f"📊 Created {len(chunks)} chunks (size: {chunk_size/(1024*1024):.1f}MB each)")
        
        return chunks
    
    def download_chunk(self, chunk_id, start, end, temp_file):
        """
        Download a single chunk with error handling and metrics.
        """
        headers = {'Range': f'bytes={start}-{end}'}
        
        # Record start time
        with self.lock:
            self.chunk_start_times[chunk_id] = time.time()
            self.active_chunks.add(chunk_id)
        
        chunk_bytes = 0
        chunk_start = time.time()
        
        try:
            with requests.get(
                self.url,
                headers=headers,
                stream=True,
                timeout=(CONNECTION_TIMEOUT, READ_TIMEOUT)
            ) as r:
                if r.status_code not in [200, 206]:
                    print(f"❌ Chunk {chunk_id}: bad status {r.status_code}")
                    with self.lock:
                        self.failed_chunks.add(chunk_id)
                        self.active_chunks.discard(chunk_id)
                    return
                
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
                self.chunk_speeds[chunk_id] = (chunk_bytes / (1024 * 1024)) / max(elapsed, 0.1)
                self.active_chunks.discard(chunk_id)
            
        except Exception as e:
            print(f"❌ Chunk {chunk_id} failed: {e}")
            with self.lock:
                self.failed_chunks.add(chunk_id)
                self.active_chunks.discard(chunk_id)
            
            # Remove partial file
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
    
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
            
            # Progress logging (every 5 seconds)
            if time.time() - last_progress_log >= 5:
                if self.downloaded_bytes > 0 and self.file_size > 0:
                    progress = (self.downloaded_bytes / self.file_size) * 100
                    speed = self.calculate_throughput()
                    print(f"📊 Progress: {progress:.1f}% | "
                          f"Active: {len(self.active_chunks)} | "
                          f"Speed: {speed:.1f} Mbps")
                last_progress_log = time.time()
            
            # Sleep to avoid busy waiting
            time.sleep(0.5)
        
        # Wait for all threads to complete
        for thread in self.threads:
            thread.join(timeout=60)
        
        success = len(self.failed_chunks) == 0
        total_time = time.time() - self.start_time
        
        print(f"✅ Download completed in {total_time:.1f}s")
        print(f"   Success rate: {(len(self.chunks) - len(self.failed_chunks)) / len(self.chunks):.1%}")
        
        return success
    
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
        for thread in self.threads:
            thread.join(timeout=300)
        
        success = len(self.failed_chunks) == 0
        total_time = time.time() - self.start_time
        
        print(f"✅ Download completed in {total_time:.1f}s")
        
        return success

    # ==================== File Assembly ====================
    
    def assemble_file(self, output_file):
        """Assemble downloaded chunks into final file."""
        print(f"📦 Assembling {len(self.temp_files)} parts...")
        
        missing_parts = [tmp for tmp in self.temp_files if not os.path.exists(tmp)]
        
        if missing_parts:
            print(f"⚠️  Missing {len(missing_parts)} parts")
        
        try:
            with open(output_file, 'wb') as out:
                for i, tmp in enumerate(self.temp_files):
                    if os.path.exists(tmp):
                        with open(tmp, 'rb') as part:
                            out.write(part.read())
                        os.remove(tmp)
            
            # Verify file size
            if os.path.exists(output_file):
                actual_size = os.path.getsize(output_file)
                if actual_size == self.file_size:
                    print("✅ File assembled and verified")
                else:
                    print(f"⚠️  Size mismatch: expected {self.file_size}, got {actual_size}")
        
        except Exception as e:
            print(f"❌ File assembly error: {e}")
    
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
            
            # Execute download strategy
            if self.use_rl:
                success = self.download_with_rl(output_path)
            else:
                success = self.download_static(output_path)
            
            if success and self.is_downloading:
                self.assemble_file(output_path)
                
                # Save RL state
                if self.use_rl:
                    self.turbolane.save()
                    stats = self.turbolane.get_stats()
                    print(f"🤖 RL Stats: {stats['q_table_size']} states, avg reward: {stats['average_reward']:.3f}")
                
                # Final metrics
                final_throughput = self.calculate_throughput()
                print(f"📈 Average throughput: {final_throughput:.2f} Mbps")
                
                return output_path
            else:
                print("❌ Download failed")
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
            'active_chunks': len(self.active_chunks)
        }
        
        if self.use_rl:
            stats['rl_stats'] = self.turbolane.get_stats()
        
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