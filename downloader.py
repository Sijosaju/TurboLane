# downloader.py - FULLY FIXED VERSION with Parallel Download Support
# Critical fixes:
# 1. Fixed thread synchronization issues
# 2. Proper chunk completion tracking
# 3. Better download loop management
# 4. Fixed assembly verification logic
# 5. Added Flask API compatibility methods
# 6. FIXED: Unique temp file names to support parallel downloads

import os
import requests
import threading
from urllib.parse import urlparse, unquote
import time
import socket
import subprocess
import platform
import uuid  # NEW: For unique download IDs
from config import *
from rl_manager import rl_manager

class MultiStreamDownloader:
    """
    Multi-stream downloader with reinforcement learning-based dynamic optimization.
    """
    
    def __init__(self, url, num_streams=DEFAULT_NUM_STREAMS, progress_callback=None, use_rl=False):
        """Initialize the downloader."""
        self.url = url
        self.num_streams = min(max(num_streams, MIN_STREAMS), MAX_STREAMS)
        self.progress_callback = progress_callback
        self.use_rl = use_rl
        
        # NEW: Unique download ID to prevent temp file collisions
        self.download_id = str(uuid.uuid4())[:8]
        
        # Download state
        self.file_size = 0
        self.chunks = []
        self.temp_files = []
        self.is_downloading = False
        self.threads = []
        self.lock = threading.Lock()
        self.start_time = None
        
        # FIXED: Track per-chunk download state
        self.chunk_states = {}  # {chunk_id: {"status": "pending/downloading/completed/failed", "bytes": int}}
        self.chunk_start_times = {}
        self.chunk_end_times = {}
        self.chunk_speeds = {}
        self.active_chunks = set()
        
        # Network metrics (paper's state variables)
        self.network_metrics = {
            "throughput": 0.0,
            "rtt": 100.0,
            "packet_loss": 0.1,
            "last_update": time.time()
        }
        
        # Packet loss smoothing
        self.last_packet_loss = 0.1
        
        # Monitoring interval tracking
        self.last_mi_time = time.time()
        self.last_mi_bytes = 0
        
        # Dynamic control for RL mode
        if self.use_rl:
            self.current_stream_count = rl_manager.current_connections
            print(f"RL Mode: Reinforcement learning optimization enabled (ID: {self.download_id})")
            print(f"Initial streams: {self.current_stream_count}")
        else:
            self.current_stream_count = self.num_streams
            print(f"Static Mode: Using {self.num_streams} streams (ID: {self.download_id})")

    def get_total_downloaded_bytes(self):
        """
        Calculate total unique downloaded bytes from chunk states.
        Prevents double-counting during retries.
        """
        with self.lock:
            total = sum(state.get("bytes", 0) for state in self.chunk_states.values() 
                       if state.get("status") in ["completed", "downloading"])
            return total

    @property
    def downloaded_bytes(self):
        """Property for Flask API compatibility - returns accurate byte count."""
        return self.get_total_downloaded_bytes()

    def get_speed(self):
        """Get current download speed in MB/s."""
        if not self.start_time:
            return 0.0
        
        elapsed = time.time() - self.start_time
        if elapsed < 0.1:
            return 0.0
        
        downloaded = self.get_total_downloaded_bytes()
        speed_mbps = (downloaded / (1024 * 1024)) / elapsed
        return speed_mbps

    def update_progress(self):
        """Update progress callback with accurate byte count."""
        if self.progress_callback:
            actual_downloaded = self.get_total_downloaded_bytes()
            self.progress_callback(actual_downloaded, self.file_size)

    # ═══════════════════════════════════════════════════════════════
    # Network Metrics
    # ═══════════════════════════════════════════════════════════════
    
    def measure_rtt(self):
        """Measure actual network RTT using ping."""
        try:
            hostname = urlparse(self.url).hostname
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            command = ['ping', param, '1', '-W', '2', hostname]
            result = subprocess.run(command, capture_output=True, text=True, timeout=3)
            output = result.stdout.lower()
            
            if 'time=' in output:
                rtt_str = output.split('time=')[1].split()[0]
                rtt = float(rtt_str.replace('ms', ''))
                return rtt
            elif 'average' in output:
                parts = output.split('/')
                if len(parts) >= 2:
                    rtt = float(parts[-1].replace('ms', '').strip())
                    return rtt
        except Exception as e:
            if ENABLE_VERBOSE_LOGGING:
                print(f"RTT measurement failed: {e}")
            return self.estimate_rtt_from_chunks()
        
        return self.estimate_rtt_from_chunks()

    def estimate_rtt_from_chunks(self):
        """Fallback RTT estimation from chunk patterns."""
        if len(self.chunk_start_times) < 2:
            return 100.0
        
        starts = sorted(self.chunk_start_times.values())
        if len(starts) < 2:
            return 100.0
        
        gaps = [starts[i+1] - starts[i] for i in range(len(starts)-1)]
        min_gap = min(gaps) if gaps else 0.1
        estimated_rtt = min(1000, max(10, min_gap * 1000))
        return estimated_rtt

    def estimate_packet_loss(self):
        """IMPROVED: More stable packet loss estimation."""
        with self.lock:
            # Count actual failed chunks
            failed_count = sum(1 for state in self.chunk_states.values() 
                             if state.get("status") == "failed")
            total_attempted = len(self.chunk_states)
            
            if total_attempted == 0:
                return 0.1
            
            # Speed variance method
            if not self.chunk_speeds or len(self.chunk_speeds) < 3:
                failure_rate = failed_count / max(1, total_attempted)
                return max(0.1, min(5.0, failure_rate * 10.0))
            
            speeds = list(self.chunk_speeds.values())
            recent_speeds = speeds[-5:] if len(speeds) >= 5 else speeds
            avg_speed = sum(recent_speeds) / len(recent_speeds)
            
            if avg_speed < 0.1:
                return 1.0
            
            variance = sum((s - avg_speed) ** 2 for s in recent_speeds) / len(recent_speeds)
            std_dev = variance ** 0.5
            cv = std_dev / avg_speed
            
            # Combine variance and actual failures
            loss_from_variance = min(1.0, cv / 2.0)
            failure_rate = failed_count / max(1, total_attempted)
            loss_from_failures = min(3.0, failure_rate * 15.0)
            estimated_loss = (loss_from_variance * 0.3) + (loss_from_failures * 0.7)
            
            # Smooth with previous value
            smoothing_factor = 0.7
            estimated_loss = (smoothing_factor * self.last_packet_loss) + \
                           ((1 - smoothing_factor) * estimated_loss)
            self.last_packet_loss = estimated_loss
            
            return max(0.1, min(5.0, estimated_loss))

    def calculate_throughput(self):
        """Calculate current throughput in Mbps."""
        if not self.start_time:
            return 0.0
        
        elapsed = time.time() - self.start_time
        if elapsed < 0.1:
            return 0.0
        
        # Use accurate byte count
        actual_bytes = self.get_total_downloaded_bytes()
        bits_downloaded = actual_bytes * 8
        throughput_bps = bits_downloaded / elapsed
        throughput_mbps = throughput_bps / (1024 * 1024)
        
        return throughput_mbps

    def update_network_metrics(self):
        """Update all network metrics for RL state."""
        current_time = time.time()
        throughput = self.calculate_throughput()
        rtt = self.measure_rtt()
        packet_loss = self.estimate_packet_loss()
        
        self.network_metrics.update({
            "throughput": throughput,
            "rtt": rtt,
            "packet_loss": packet_loss,
            "last_update": current_time
        })
        
        if LOG_NETWORK_METRICS:
            print(f"[{self.download_id}] Network Metrics: T={throughput:.2f}Mbps, RTT={rtt:.1f}ms, Loss={packet_loss:.2f}%")
        
        return throughput, rtt, packet_loss

    # ═══════════════════════════════════════════════════════════════
    # RL Integration
    # ═══════════════════════════════════════════════════════════════
    
    def should_run_mi(self):
        """Check if a Monitoring Interval (MI) should run."""
        return time.time() - self.last_mi_time >= RL_MONITORING_INTERVAL

    def run_monitoring_interval(self):
        """Execute one monitoring interval cycle."""
        if not self.use_rl or not self.should_run_mi():
            return
        
        try:
            throughput, rtt, packet_loss = self.update_network_metrics()
            rl_manager.learn_from_feedback(throughput, rtt, packet_loss)
            new_stream_count = rl_manager.make_decision(throughput, rtt, packet_loss)
            
            if new_stream_count != self.current_stream_count:
                old_count = self.current_stream_count
                self.current_stream_count = new_stream_count
                print(f"[{self.download_id}] Stream count adjusted: {old_count} → {new_stream_count}")
            
            self.last_mi_time = time.time()
            self.last_mi_bytes = self.get_total_downloaded_bytes()
            
        except Exception as e:
            print(f"[{self.download_id}] MI execution error: {e}")

    # ═══════════════════════════════════════════════════════════════
    # Chunk Management (FIXED)
    # ═══════════════════════════════════════════════════════════════
    
    def get_filename_from_url(self):
        """Extract filename from URL."""
        path = urlparse(self.url).path
        filename = unquote(os.path.basename(path))
        return filename if filename else "downloaded_file"

    def check_download_support(self):
        """Check if server supports range requests."""
        try:
            response = requests.head(self.url, timeout=CONNECTION_TIMEOUT, allow_redirects=True)
            supports_ranges = response.headers.get('Accept-Ranges') == 'bytes'
            file_size = int(response.headers.get('Content-Length', 0))
            
            content_disposition = response.headers.get('Content-Disposition', '')
            filename = content_disposition.split('filename=')[1].strip('"') if 'filename=' in content_disposition else self.get_filename_from_url()
            
            return supports_ranges, file_size, filename
        except Exception as e:
            print(f"[{self.download_id}] HEAD request failed, trying range request: {e}")
            try:
                headers = {'Range': 'bytes=0-0'}
                response = requests.get(self.url, headers=headers, timeout=CONNECTION_TIMEOUT, stream=True)
                supports_ranges = response.status_code == 206
                
                if 'Content-Range' in response.headers:
                    file_size = int(response.headers['Content-Range'].split('/')[-1])
                else:
                    file_size = int(response.headers.get('Content-Length', 0))
                
                filename = self.get_filename_from_url()
                response.close()
                
                return supports_ranges, file_size, filename
            except Exception as e2:
                print(f"[{self.download_id}] Range request also failed: {e2}")
                return False, 0, self.get_filename_from_url()

    def calculate_chunks(self, file_size, max_streams):
        """Divide file into chunks for parallel download."""
        min_chunk_size = max(MIN_CHUNK_SIZE, 1024 * 1024)
        
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
            
            # FIXED: Initialize chunk state
            self.chunk_states[i] = {
                "status": "pending",
                "bytes": 0,
                "expected_size": end - start + 1
            }
        
        print(f"[{self.download_id}] Created {len(chunks)} chunks (~{chunk_size/(1024*1024):.1f}MB each)")
        return chunks

    def download_chunk(self, chunk_id, start, end, temp_file):
        """FIXED: Download a single chunk with proper state tracking and completion."""
        
        headers = {'Range': f'bytes={start}-{end}'}
        expected_size = end - start + 1
        
        # FIXED: Reset chunk state for retry
        with self.lock:
            self.chunk_states[chunk_id] = {
                "status": "downloading",
                "bytes": 0,
                "expected_size": expected_size
            }
            self.chunk_start_times[chunk_id] = time.time()
            self.active_chunks.add(chunk_id)
        
        chunk_bytes = 0
        chunk_start = time.time()
        download_cancelled = False
        
        try:
            with requests.get(self.url, headers=headers, stream=True, 
                            timeout=(CONNECTION_TIMEOUT, READ_TIMEOUT)) as r:
                if r.status_code not in [200, 206]:
                    print(f"[{self.download_id}] Chunk {chunk_id}: bad status {r.status_code}")
                    with self.lock:
                        self.chunk_states[chunk_id]["status"] = "failed"
                        self.chunk_states[chunk_id]["bytes"] = 0
                        self.active_chunks.discard(chunk_id)
                    return
                
                with open(temp_file, 'wb') as f:
                    for data in r.iter_content(chunk_size=BUFFER_SIZE):
                        if not self.is_downloading:
                            download_cancelled = True
                            break
                        f.write(data)
                        chunk_bytes += len(data)
                        
                        # FIXED: Update chunk state instead of global counter
                        with self.lock:
                            self.chunk_states[chunk_id]["bytes"] = chunk_bytes
                        
                        self.update_progress()
            
            # CRITICAL FIX: If cancelled, mark as failed
            if download_cancelled:
                print(f"[{self.download_id}] Chunk {chunk_id}: download cancelled")
                with self.lock:
                    self.chunk_states[chunk_id]["status"] = "failed"
                    self.chunk_states[chunk_id]["bytes"] = 0
                    self.active_chunks.discard(chunk_id)
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                return
            
            # Verify chunk size
            if chunk_bytes != expected_size:
                print(f"[{self.download_id}] Chunk {chunk_id}: size mismatch (got {chunk_bytes}, expected {expected_size})")
                with self.lock:
                    self.chunk_states[chunk_id]["status"] = "failed"
                    self.chunk_states[chunk_id]["bytes"] = 0
                    self.active_chunks.discard(chunk_id)
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                return
            
            # Success - mark as completed
            chunk_end = time.time()
            elapsed = chunk_end - chunk_start
            
            with self.lock:
                self.chunk_states[chunk_id]["status"] = "completed"
                self.chunk_end_times[chunk_id] = chunk_end
                self.chunk_speeds[chunk_id] = (chunk_bytes / (1024 * 1024)) / max(elapsed, 0.1)
                self.active_chunks.discard(chunk_id)
            
            if ENABLE_VERBOSE_LOGGING:
                print(f"[{self.download_id}] Chunk {chunk_id}: completed ({chunk_bytes/(1024*1024):.2f} MB in {elapsed:.1f}s)")
                
        except Exception as e:
            print(f"[{self.download_id}] Chunk {chunk_id} failed: {e}")
            with self.lock:
                self.chunk_states[chunk_id]["status"] = "failed"
                self.chunk_states[chunk_id]["bytes"] = 0  # Don't count partial bytes
                self.active_chunks.discard(chunk_id)
            
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

    def start_chunk_download(self, chunk_id, output_path):
        """Start downloading a specific chunk in a new thread."""
        if chunk_id >= len(self.chunks):
            return
        
        # FIXED: Don't re-download completed chunks
        with self.lock:
            if self.chunk_states[chunk_id]["status"] == "completed":
                return
        
        start, end = self.chunks[chunk_id]
        # CRITICAL FIX: Add download_id to prevent collisions
        temp_file = f"{output_path}.{self.download_id}.part{chunk_id}"
        
        if temp_file not in self.temp_files:
            self.temp_files.append(temp_file)
        
        thread = threading.Thread(
            target=self.download_chunk,
            args=(chunk_id, start, end, temp_file),
            daemon=True
        )
        thread.start()
        self.threads.append(thread)

    def get_pending_chunks(self):
        """Get list of chunks that need to be downloaded."""
        with self.lock:
            return [chunk_id for chunk_id, state in self.chunk_states.items()
                   if state["status"] in ["pending", "failed"]]

    # ═══════════════════════════════════════════════════════════════
    # Download Strategies
    # ═══════════════════════════════════════════════════════════════
    
    def download_with_rl(self, output_path):
        """RL-based adaptive multi-stream download."""
        print(f"[{self.download_id}] Starting RL-based adaptive download...")
        self.is_downloading = True
        self.start_time = time.time()
        self.last_mi_time = self.start_time
        self.threads, self.temp_files = [], []
        
        # Create chunks
        self.chunks = self.calculate_chunks(self.file_size, MAX_STREAMS)
        
        # Start initial chunks
        pending = self.get_pending_chunks()
        initial_streams = min(self.current_stream_count, len(pending))
        print(f"[{self.download_id}] Starting with {initial_streams} streams")
        
        for _ in range(initial_streams):
            if pending:
                chunk_id = pending.pop()
                self.start_chunk_download(chunk_id, output_path)
        
        # Main download loop
        last_progress_log = time.time()
        while self.is_downloading:
            # Run monitoring interval
            self.run_monitoring_interval()
            
            # Clean up completed threads
            self.threads = [t for t in self.threads if t.is_alive()]
            
            # Check if done
            pending = self.get_pending_chunks()
            if not pending and not self.threads:
                break  # All chunks downloaded
            
            # Start new chunks if slots available
            active_threads = len(self.threads)
            available_slots = self.current_stream_count - active_threads
            
            if available_slots > 0 and pending:
                chunks_to_start = min(available_slots, len(pending))
                for _ in range(chunks_to_start):
                    if pending:
                        chunk_id = pending.pop()
                        self.start_chunk_download(chunk_id, output_path)
            
            # Progress logging
            if time.time() - last_progress_log >= 5:
                actual_bytes = self.get_total_downloaded_bytes()
                if actual_bytes > 0 and self.file_size > 0:
                    progress = (actual_bytes / self.file_size) * 100
                    speed = self.calculate_throughput()
                    print(f"[{self.download_id}] Progress: {progress:.1f}% | Active: {len(self.active_chunks)} | Speed: {speed:.1f} Mbps")
                last_progress_log = time.time()
            
            time.sleep(0.5)
        
        # CRITICAL FIX: Wait for ALL threads to complete
        print(f"[{self.download_id}] Waiting for all download threads to complete...")
        for thread in self.threads:
            thread.join()  # No timeout - wait indefinitely
        
        # Check success
        with self.lock:
            failed = sum(1 for state in self.chunk_states.values() 
                        if state["status"] == "failed")
            completed = sum(1 for state in self.chunk_states.values() 
                           if state["status"] == "completed")
            success = failed == 0 and completed == len(self.chunks)
        
        total_time = time.time() - self.start_time
        print(f"[{self.download_id}] Download phase completed in {total_time:.1f}s")
        print(f"[{self.download_id}] Completed: {completed}/{len(self.chunks)}, Failed: {failed}")
        
        return success

    def download_static(self, output_path):
        """Traditional static multi-stream download."""
        print(f"[{self.download_id}] Starting static download with {self.num_streams} streams...")
        self.is_downloading = True
        self.start_time = time.time()
        
        self.chunks = self.calculate_chunks(self.file_size, self.num_streams)
        
        for i in range(len(self.chunks)):
            self.start_chunk_download(i, output_path)
        
        # CRITICAL FIX: Wait for ALL threads without timeout
        print(f"[{self.download_id}] Waiting for all download threads to complete...")
        for thread in self.threads:
            thread.join()  # No timeout - wait indefinitely
        
        # Check success
        with self.lock:
            failed = sum(1 for state in self.chunk_states.values() 
                        if state["status"] == "failed")
            completed = sum(1 for state in self.chunk_states.values() 
                           if state["status"] == "completed")
            success = failed == 0 and completed == len(self.chunks)
        
        total_time = time.time() - self.start_time
        print(f"[{self.download_id}] Download phase completed in {total_time:.1f}s")
        print(f"[{self.download_id}] Completed: {completed}/{len(self.chunks)}, Failed: {failed}")
        
        return success

    def retry_failed_chunks(self, output_path, max_retries=3):
        """FIXED: Retry failed chunks without double-counting bytes."""
        with self.lock:
            failed_ids = [chunk_id for chunk_id, state in self.chunk_states.items()
                         if state["status"] == "failed"]
        
        if not failed_ids:
            return True
        
        print(f"[{self.download_id}] Retrying {len(failed_ids)} failed chunks...")
        
        for retry_attempt in range(max_retries):
            if not failed_ids:
                break
            
            print(f"[{self.download_id}] Retry attempt {retry_attempt + 1}/{max_retries}")
            
            threads = []
            for chunk_id in list(failed_ids):
                if chunk_id >= len(self.chunks):
                    continue
                
                start, end = self.chunks[chunk_id]
                # CRITICAL FIX: Use download_id in temp file name
                temp_file = f"{output_path}.{self.download_id}.part{chunk_id}"
                
                print(f"[{self.download_id}] Retrying chunk {chunk_id}...")
                thread = threading.Thread(
                    target=self.download_chunk,
                    args=(chunk_id, start, end, temp_file),
                    daemon=True
                )
                thread.start()
                threads.append(thread)
            
            # Wait for all retry threads
            for thread in threads:
                thread.join()
            
            # Update failed list
            with self.lock:
                failed_ids = [chunk_id for chunk_id, state in self.chunk_states.items()
                            if state["status"] == "failed"]
            
            if not failed_ids:
                print(f"[{self.download_id}] All chunks recovered after {retry_attempt + 1} attempts")
                return True
            else:
                print(f"[{self.download_id}] Still {len(failed_ids)} chunks failed")
                time.sleep(1)
        
        if failed_ids:
            print(f"[{self.download_id}] Failed to recover {len(failed_ids)} chunks after {max_retries} retries")
            print(f"[{self.download_id}] Failed chunk IDs: {sorted(failed_ids)}")
            return False
        
        return True

    # ═══════════════════════════════════════════════════════════════
    # File Assembly (FIXED)
    # ═══════════════════════════════════════════════════════════════
    
    def assemble_file(self, output_file):
        """FIXED: Assemble with proper verification."""
        print("="*70)
        print(f"[{self.download_id}] ASSEMBLING FILE")
        print("="*70)
        
        # Verify all chunks are completed
        with self.lock:
            total_chunks = len(self.chunks)
            completed = sum(1 for state in self.chunk_states.values() 
                          if state["status"] == "completed")
            failed = sum(1 for state in self.chunk_states.values() 
                        if state["status"] == "failed")
            downloading = sum(1 for state in self.chunk_states.values() 
                            if state["status"] == "downloading")
        
        print(f"[{self.download_id}] Total chunks: {total_chunks}")
        print(f"[{self.download_id}] Completed: {completed}")
        print(f"[{self.download_id}] Failed: {failed}")
        print(f"[{self.download_id}] Still downloading: {downloading}")
        
        try:
            # Retry failed chunks
            if failed > 0:
                print(f"[{self.download_id}] Attempting to recover {failed} failed chunks...")
                success = self.retry_failed_chunks(output_file)
                if not success:
                    print(f"[{self.download_id}] Cannot assemble: failed chunks not recovered")
                    return False
            
            # CRITICAL FIX: Also retry chunks stuck in "downloading" state
            if downloading > 0:
                print(f"[{self.download_id}] WARNING: {downloading} chunks still in 'downloading' state")
                with self.lock:
                    for chunk_id, state in self.chunk_states.items():
                        if state["status"] == "downloading":
                            state["status"] = "failed"  # Mark as failed to retry
                
                print(f"[{self.download_id}] Retrying incomplete chunks...")
                success = self.retry_failed_chunks(output_file)
                if not success:
                    print(f"[{self.download_id}] Cannot assemble: incomplete chunks not recovered")
                    return False
            
            # Verify all chunks are completed
            with self.lock:
                all_completed = all(state["status"] == "completed" 
                                  for state in self.chunk_states.values())
            
            if not all_completed:
                with self.lock:
                    status_counts = {}
                    for state in self.chunk_states.values():
                        status = state["status"]
                        status_counts[status] = status_counts.get(status, 0) + 1
                print(f"[{self.download_id}] Not all chunks completed. Status breakdown: {status_counts}")
                return False
            
            # Assemble file
            print(f"[{self.download_id}] Assembling chunks into final file...")
            assembled_bytes = 0
            
            with open(output_file, 'wb') as out:
                for i in range(len(self.chunks)):
                    # CRITICAL FIX: Use download_id in temp file name
                    temp_file = f"{output_file}.{self.download_id}.part{i}"
                    
                    if not os.path.exists(temp_file):
                        print(f"[{self.download_id}] CRITICAL: Chunk {i} missing during assembly!")
                        print(f"[{self.download_id}] Expected file: {temp_file}")
                        return False
                    
                    with open(temp_file, 'rb') as part:
                        chunk_data = part.read()
                        out.write(chunk_data)
                        assembled_bytes += len(chunk_data)
                    
                    try:
                        os.remove(temp_file)
                    except Exception as e:
                        print(f"[{self.download_id}] Could not remove {temp_file}: {e}")
            
            # Verify final file
            if os.path.exists(output_file):
                actual_size = os.path.getsize(output_file)
                
                print("="*70)
                print(f"[{self.download_id}] ASSEMBLY VERIFICATION")
                print("="*70)
                print(f"[{self.download_id}] Expected size: {self.file_size:,} bytes ({self.file_size/(1024*1024):.2f} MB)")
                print(f"[{self.download_id}] Actual size: {actual_size:,} bytes ({actual_size/(1024*1024):.2f} MB)")
                
                if actual_size == self.file_size:
                    print(f"[{self.download_id}] ✓ PERFECT MATCH - File assembled successfully!")
                    print("="*70)
                    return True
                else:
                    size_diff_pct = abs(actual_size - self.file_size) / self.file_size * 100
                    print(f"[{self.download_id}] ✗ SIZE MISMATCH - {size_diff_pct:.2f}% difference")
                    print("="*70)
                    return False
            else:
                print(f"[{self.download_id}] Output file not created!")
                return False
                
        except Exception as e:
            print(f"[{self.download_id}] File assembly error: {e}")
            import traceback
            traceback.print_exc()
            return False

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
        print(f"[{self.download_id}] Cancelling download...")
        self.is_downloading = False
        time.sleep(1)
        self.cleanup()

    def get_stats(self):
        """Get download statistics."""
        elapsed = time.time() - self.start_time if self.start_time else 0
        
        # Use accurate byte count
        actual_downloaded = self.get_total_downloaded_bytes()
        
        with self.lock:
            completed_count = sum(1 for state in self.chunk_states.values() 
                                if state["status"] == "completed")
            failed_count = sum(1 for state in self.chunk_states.values() 
                             if state["status"] == "failed")
            active_count = len(self.active_chunks)
        
        stats = {
            "elapsed_time": elapsed,
            "downloaded_bytes": actual_downloaded,
            "file_size": self.file_size,
            "progress": (actual_downloaded / self.file_size * 100) if self.file_size > 0 else 0,
            "throughput_mbps": self.calculate_throughput(),
            "num_chunks": len(self.chunks),
            "completed_chunks": completed_count,
            "failed_chunks": failed_count,
            "active_chunks": active_count
        }
        
        if self.use_rl:
            stats["rl_stats"] = rl_manager.get_stats()
        
        return stats

    def get_detailed_metrics(self):
        """Get detailed download metrics for API."""
        stats = self.get_stats()
        
        detailed_stats = {
            **stats,
            "current_stream_count": self.current_stream_count,
            "use_rl": self.use_rl,
            "url": self.url,
            "is_downloading": self.is_downloading,
            "network_metrics": self.network_metrics.copy(),
            "chunk_progress": {
                "total": len(self.chunks),
                "completed": stats["completed_chunks"],
                "failed": stats["failed_chunks"],
                "active": stats["active_chunks"]
            }
        }
        
        return detailed_stats

    # ═══════════════════════════════════════════════════════════════
    # Main Entry Point
    # ═══════════════════════════════════════════════════════════════
    
    def download(self, output_path=None):
        """Main download function."""
        try:
            print(f"[{self.download_id}] Checking server support...")
            supports_ranges, file_size, filename = self.check_download_support()
            self.file_size = file_size
            
            if not supports_ranges:
                print(f"[{self.download_id}] Range requests not supported, using single stream")
                self.num_streams = 1
                self.use_rl = False
            
            output_path = output_path or os.path.join(DOWNLOAD_FOLDER, filename)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            print(f"[{self.download_id}] Output: {output_path}")
            print(f"[{self.download_id}] Size: {file_size / (1024*1024):.1f} MB")
            
            # Execute download
            if self.use_rl:
                download_success = self.download_with_rl(output_path)
            else:
                download_success = self.download_static(output_path)
            
            if not self.is_downloading:
                print(f"[{self.download_id}] Download cancelled by user")
                self.cleanup()
                return None
            
            # Assemble file
            print("="*70)
            print(f"[{self.download_id}] Starting file assembly...")
            print("="*70)
            assembly_success = self.assemble_file(output_path)
            
            if assembly_success:
                if self.use_rl:
                    rl_manager.save_q_table()
                    rl_manager.print_stats()
                
                final_throughput = self.calculate_throughput()
                total_time = time.time() - self.start_time
                
                print("="*70)
                print(f"[{self.download_id}] DOWNLOAD COMPLETE")
                print("="*70)
                print(f"[{self.download_id}] File: {output_path}")
                print(f"[{self.download_id}] Size: {self.file_size / (1024*1024):.2f} MB")
                print(f"[{self.download_id}] Time: {total_time:.1f}s")
                print(f"[{self.download_id}] Avg Speed: {final_throughput:.2f} Mbps")
                
                with self.lock:
                    success_chunks = sum(1 for state in self.chunk_states.values() 
                                       if state["status"] == "completed")
                print(f"[{self.download_id}] Success rate: {(success_chunks / len(self.chunks) * 100):.1f}%")
                print("="*70)
                
                return output_path
            else:
                print("="*70)
                print(f"[{self.download_id}] DOWNLOAD FAILED - Assembly Error")
                print("="*70)
                
                with self.lock:
                    failed_count = sum(1 for state in self.chunk_states.values() 
                                     if state["status"] == "failed")
                    failed_ids = [chunk_id for chunk_id, state in self.chunk_states.items()
                                if state["status"] == "failed"]
                
                print(f"[{self.download_id}] Failed chunks after retry: {failed_count}/{len(self.chunks)}")
                if failed_ids:
                    print(f"[{self.download_id}] Failed chunk IDs: {sorted(failed_ids)[:10]}")
                print("="*70)
                
                self.cleanup()
                return None
                
        except Exception as e:
            print(f"[{self.download_id}] Download error: {e}")
            import traceback
            traceback.print_exc()
            self.cleanup()
            return None
