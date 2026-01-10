"""
DCI Client Module - ULTIMATE VERSION with PPO Support
Refactored to use TurboLane Engine abstraction (unified with downloader).
"""

import socket
import threading
import logging
import time
import struct
import os
from pathlib import Path
from typing import Optional, List
from queue import Queue, Empty
from dataclasses import dataclass
from collections import deque

from . import config
from . import protocol

# Configure logging
logging.basicConfig(
    level=config.LOG_LEVEL,
    format=config.LOG_FORMAT
)

logger = logging.getLogger(__name__)

# Import turbolane engine abstraction
try:
    from turbolane import TurboLaneEngine
    RL_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Turbolane engine not available: {e}")
    RL_AVAILABLE = False


@dataclass
class StreamTask:
    """Task for individual stream worker."""
    stream_id: int
    offset: int
    size: int


@dataclass
class TransferMetrics:
    """Real-time metrics for RL feedback."""
    bytes_sent: int = 0
    last_measurement_time: float = 0
    last_measurement_bytes: int = 0
    current_throughput_mbps: float = 0
    lock: threading.Lock = None
    
    def __post_init__(self):
        if self.lock is None:
            self.lock = threading.Lock()


class StreamWorkerPool:
    """
    Dynamic worker pool that can spawn/kill streams during transfer.
    This is the KEY to adaptive performance.
    """
    
    def __init__(self, task_queue: Queue, filepath: Path, transfer_id: str,
                 server_host: str, server_port: int, metrics: TransferMetrics):
        self.task_queue = task_queue
        self.filepath = filepath
        self.transfer_id = transfer_id
        self.server_host = server_host
        self.server_port = server_port
        self.metrics = metrics
        
        self.workers: List[threading.Thread] = []
        self.stop_flags: List[threading.Event] = []
        self.success_flags: List[bool] = []
        self.lock = threading.Lock()
        self.next_stream_id = 0
    
    def spawn_workers(self, count: int):
        """Spawn new worker threads dynamically."""
        with self.lock:
            for _ in range(count):
                stop_flag = threading.Event()
                success_idx = len(self.success_flags)
                self.success_flags.append(True)
                
                worker = threading.Thread(
                    target=self.worker_loop,
                    args=(self.next_stream_id, stop_flag, success_idx),
                    daemon=True
                )
                
                self.workers.append(worker)
                self.stop_flags.append(stop_flag)
                worker.start()
                
                logger.info(f"✅ Spawned stream {self.next_stream_id}")
                self.next_stream_id += 1
    
    def kill_workers(self, count: int):
        """Kill excess workers gracefully."""
        with self.lock:
            active_indices = [i for i, flag in enumerate(self.stop_flags) if not flag.is_set()]
            kill_count = min(count, len(active_indices))
            
            for i in range(kill_count):
                idx = active_indices[i]
                self.stop_flags[idx].set()
                logger.info(f"🔻 Killing stream {idx}")
    
    def get_active_count(self) -> int:
        """Count currently active workers."""
        with self.lock:
            return sum(1 for flag in self.stop_flags if not flag.is_set())
    
    def wait_completion(self):
        """Block until all workers finish."""
        for worker in self.workers:
            worker.join()
    
    def all_successful(self) -> bool:
        """Check if all workers succeeded."""
        return all(self.success_flags)
    
    def worker_loop(self, stream_id: int, stop_flag: threading.Event, success_idx: int):
        """Worker thread that processes chunks until stopped."""
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(300.0)  # 5 minute timeout
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            
            # Windows-specific TCP keepalive settings
            if hasattr(socket, 'SIO_KEEPALIVE_VALS'):
                sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 60000, 30000))
            
            sock.connect((self.server_host, self.server_port))
            
            with open(self.filepath, 'rb') as f:
                INFLIGHT_WINDOW = 4
                pending_acks = 0
                
                while not stop_flag.is_set():
                    try:
                        task = self.task_queue.get(timeout=1)
                    except Empty:
                        break  # No more tasks available
                    
                    # Read chunk
                    f.seek(task.offset)
                    data = f.read(task.size)
                    
                    # Send chunk
                    chunk = protocol.ChunkData(
                        transfer_id=self.transfer_id,
                        stream_id=stream_id,
                        offset=task.offset,
                        data=data
                    )
                    sock.sendall(chunk.to_message().serialize())
                    
                    # Update metrics for RL
                    with self.metrics.lock:
                        self.metrics.bytes_sent += len(data)
                    
                    pending_acks += 1
                    
                    # Wait for ACK with timeout
                    if pending_acks >= INFLIGHT_WINDOW:
                        try:
                            sock.settimeout(30.0)  # 30 second timeout for ACK
                            ack_header = protocol.receive_exact(sock, 14)
                            _, _, _, ack_len = struct.unpack('!8sBBI', ack_header)
                            if ack_len > 0:
                                protocol.receive_exact(sock, ack_len)
                            pending_acks -= 1
                            sock.settimeout(300.0)  # Restore long timeout
                        except socket.timeout:
                            logger.warning(f"Stream {stream_id}: ACK timeout, continuing...")
                        except Exception as e:
                            logger.debug(f"Stream {stream_id}: ACK error (non-fatal): {e}")
                    
                    self.task_queue.task_done()
                
                # Wait for final ACKs
                while pending_acks > 0:
                    try:
                        sock.settimeout(30.0)
                        ack_header = protocol.receive_exact(sock, 14)
                        _, _, _, ack_len = struct.unpack('!8sBBI', ack_header)
                        if ack_len > 0:
                            protocol.receive_exact(sock, ack_len)
                        pending_acks -= 1
                    except socket.timeout:
                        logger.warning(f"Stream {stream_id}: Final ACK timeout, continuing...")
                        break
                    except Exception as e:
                        logger.debug(f"Stream {stream_id}: Final ACK error (non-fatal): {e}")
                        break
                
                logger.debug(f"Stream {stream_id} completed successfully")
                
        except Exception as e:
            logger.error(f"Stream {stream_id} error: {e}")
            self.success_flags[success_idx] = False
        finally:
            if sock:
                sock.close()


class DCIClient:
    """
    DCI file transfer client with FULLY DYNAMIC RL-based stream adjustment.
    Uses TurboLane Engine abstraction for unified architecture.
    """
    
    def __init__(self, server_host: str, server_port: int = config.DEFAULT_SERVER_PORT):
        self.server_host = server_host
        self.server_port = server_port
        self.transfer_id = None
        self.transfer_complete = False
        
        self.rl_enabled = config.RL_ENABLED and RL_AVAILABLE
        self.algorithm = config.RL_ALGORITHM.lower() if hasattr(config, 'RL_ALGORITHM') else 'ppo'
        
        # Initialize directories
        config.initialize_directories()
        
        if self.rl_enabled:
            # Initialize TurboLane Engine in DCI mode
            self.turbolane = TurboLaneEngine(
                mode='dci',
                algorithm=self.algorithm,
                model_dir=config.get_model_path(),
                state_size=5,
                action_size=3,
                learning_rate=getattr(config, 'PPO_LEARNING_RATE', 0.001) if self.algorithm == 'ppo' else 0.1,
                discount_factor=getattr(config, 'PPO_GAMMA', 0.99) if self.algorithm == 'ppo' else 0.8,
                epsilon=0.3,
                epsilon_decay=0.995,
                epsilon_min=0.05,
                min_connections=config.RL_MIN_STREAMS,
                max_connections=config.RL_MAX_STREAMS,
                default_connections=config.RL_INITIAL_STREAMS
            )
            logger.info(f"🚀 RL acceleration enabled ({self.algorithm.upper()} algorithm)")
            logger.info(f"   Model path: {config.get_model_path()}")
            logger.info(f"   Engine: TurboLane DCI mode")
        else:
            self.turbolane = None
            logger.warning("⚠️ RL acceleration disabled")
        
        self.metrics = TransferMetrics()
        self.stop_monitoring = threading.Event()
        self.worker_pool = None
    
    def send_file(self, filepath: Path, num_streams: Optional[int] = None) -> bool:
        """
        Send file with dynamic stream adjustment.
        
        Args:
            filepath: File to send
            num_streams: Initial streams (None = RL decides)
            
        Returns:
            True if successful
        """
        if not filepath.exists():
            logger.error(f"File not found: {filepath}")
            return False
        
        filesize = filepath.stat().st_size
        logger.info(f"📁 Preparing to send {filepath.name} ({filesize} bytes)")
        
        # Compute checksum
        logger.info("🔐 Computing file checksum...")
        checksum = protocol.compute_file_checksum(filepath)
        logger.info(f"   Checksum: {checksum}")
        
        # Determine initial streams
        if num_streams is None:
            if self.rl_enabled:
                num_streams = self.turbolane.get_current_connections()
            else:
                num_streams = config.RL_INITIAL_STREAMS
        
        num_streams = max(config.RL_MIN_STREAMS, min(num_streams, config.RL_MAX_STREAMS))
        
        if self.rl_enabled:
            self.turbolane.set_connections(num_streams)
        
        logger.info(f"🚀 Starting with {num_streams} parallel streams")
        
        # Send transfer request
        if not self._send_transfer_request(filepath.name, filesize, checksum, num_streams):
            return False
        
        # Initialize metrics
        self.metrics = TransferMetrics()
        self.metrics.last_measurement_time = time.time()
        self.stop_monitoring.clear()
        
        # Create task queue
        chunk_size = config.CHUNK_SIZE
        task_queue = Queue()
        offset = 0
        task_id = 0
        
        while offset < filesize:
            size = min(chunk_size, filesize - offset)
            task_queue.put(StreamTask(task_id, offset, size))
            offset += size
            task_id += 1
        
        logger.info(f"📋 Created {task_queue.qsize()} transfer tasks")
        
        # Create dynamic worker pool
        self.worker_pool = StreamWorkerPool(
            task_queue=task_queue,
            filepath=filepath,
            transfer_id=self.transfer_id,
            server_host=self.server_host,
            server_port=self.server_port,
            metrics=self.metrics
        )
        
        # Spawn initial workers
        self.worker_pool.spawn_workers(num_streams)
        
        # Start adaptive monitoring thread
        monitor_thread = None
        if self.rl_enabled:
            monitor_thread = threading.Thread(
                target=self.adaptive_monitor,
                args=(filesize,),
                daemon=True
            )
            monitor_thread.start()
            logger.info("🔍 Adaptive monitoring started")
        
        # Wait for transfer to complete
        start_time = time.time()
        self.worker_pool.wait_completion()
        self.transfer_complete = True
        elapsed = time.time() - start_time
        
        # Stop monitoring
        self.stop_monitoring.set()
        if monitor_thread:
            monitor_thread.join(timeout=2)
        
        # Check success
        success = self.worker_pool.all_successful()
        
        if success:
            throughput = (filesize / elapsed) / (1024 * 1024)
            final_streams = self.worker_pool.get_active_count()
            
            logger.info("=" * 60)
            logger.info("✅ Transfer complete!")
            logger.info(f"   File: {filepath.name}")
            logger.info(f"   Size: {filesize} bytes")
            logger.info(f"   Time: {elapsed:.2f}s")
            logger.info(f"   Throughput: {throughput:.2f} MB/s")
            logger.info(f"   Initial streams: {num_streams}")
            logger.info(f"   Final streams: {final_streams}")
            logger.info(f"   Algorithm: {self.algorithm.upper()}")
            logger.info("=" * 60)
            
            # Save policy state
            if self.rl_enabled:
                self.turbolane.save()
                stats = self.turbolane.get_stats()
                logger.info(f"💾 Policy saved: {stats}")
        else:
            logger.error("❌ Transfer failed")
        
        return success
    
    def adaptive_monitor(self, total_filesize: int):
        """
        Monitor thread that uses TurboLane engine to make adaptive decisions.
        This is where the magic happens - streams are adjusted in real-time!
        """
        logger.info(f"🔍 Starting adaptive monitoring with {self.algorithm.upper()} algorithm...")
        
        # Tracking for state history
        throughput_history = deque(maxlen=5)
        rtt_history = deque(maxlen=5)
        loss_history = deque(maxlen=5)
        
        last_decision_time = time.time()
        monitoring_interval = 5.0  # Paper's Monitoring Interval (MI)
        
        # For reward calculation
        last_state = None
        last_action = None
        
        while not self.stop_monitoring.is_set():
            current_time = time.time()
            
            # Check if it's time for a monitoring interval
            if current_time - last_decision_time < monitoring_interval:
                time.sleep(0.5)
                continue
            
            if self.transfer_complete:
                logger.info("✅ Transfer complete - freezing RL decisions")
                break
            
            if self.stop_monitoring.is_set():
                break
            
            with self.metrics.lock:
                time_delta = current_time - self.metrics.last_measurement_time
                
                if time_delta < 1.0:
                    continue  # Too soon to measure accurately
                
                bytes_delta = self.metrics.bytes_sent - self.metrics.last_measurement_bytes
                throughput_mbps = (bytes_delta / time_delta) / (1024 * 1024)
                self.metrics.current_throughput_mbps = throughput_mbps
            
            # Store in history
            throughput_history.append(throughput_mbps)
            rtt_history.append(50.0)  # Assume datacenter link
            loss_history.append(0.1 if throughput_mbps > 100 else 0.5)
            
            # Calculate progress
            progress = (self.metrics.bytes_sent / total_filesize) * 100
            current_streams = self.worker_pool.get_active_count()
            
            logger.info(f"📈 Progress: {progress:.1f}% | "
                       f"Throughput: {throughput_mbps:.2f} MB/s | "
                       f"Active streams: {current_streams}")
            
            # Estimate network metrics
            estimated_rtt = 50.0  # Assume datacenter link
            estimated_loss = 0.1 if throughput_mbps > 100 else 0.5
            
            # Build state
            state = (
                int(throughput_mbps / 20),    # Discretize throughput
                int(estimated_rtt / 50),       # Discretize RTT
                int(estimated_loss * 10)       # Discretize loss
            )
            
            # Get action from TurboLane engine
            desired_streams = self.turbolane.select_action(
                state=state,
                current_connections=current_streams,
                explore=True
            )
            
            # Apply action
            stream_diff = desired_streams - current_streams
            
            if stream_diff > 0:
                logger.info(f"🔧 RL Decision: SCALE UP by {stream_diff} streams "
                           f"({current_streams} → {desired_streams})")
                self.worker_pool.spawn_workers(stream_diff)
            elif stream_diff < 0:
                logger.info(f"🔧 RL Decision: SCALE DOWN by {-stream_diff} streams "
                           f"({current_streams} → {desired_streams})")
                self.worker_pool.kill_workers(-stream_diff)
            else:
                logger.debug(f"🔧 RL Decision: MAINTAIN {current_streams} streams")
            
            # Calculate reward and learn
            if last_state is not None and last_action is not None:
                # Simple reward: positive if throughput increased
                reward = 1.0 if throughput_mbps > self.metrics.last_measurement_bytes else -1.0
                
                # Update TurboLane engine
                self.turbolane.update(
                    state=last_state,
                    action=last_action,
                    reward=reward,
                    next_state=state,
                    done=False
                )
                
                # Train step for PPO
                if self.algorithm == 'ppo':
                    loss = self.turbolane.train_step()
                    if loss is not None:
                        logger.debug(f"PPO training loss: {loss:.4f}")
            
            # Store for next iteration
            last_state = state
            last_action = 0 if stream_diff < 0 else (2 if stream_diff > 0 else 1)
            
            # Update measurement baseline
            self.metrics.last_measurement_time = current_time
            self.metrics.last_measurement_bytes = self.metrics.bytes_sent
            last_decision_time = current_time
        
        logger.info("🛑 Adaptive monitoring stopped")
    
    def _send_transfer_request(self, filename: str, filesize: int,
                              checksum: str, num_streams: int) -> bool:
        """Send initial transfer request to server."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((self.server_host, self.server_port))
            
            request = protocol.TransferRequest(
                filename=filename,
                filesize=filesize,
                checksum=checksum,
                num_streams=num_streams
            )
            sock.sendall(request.to_message().serialize())
            
            # Wait for response
            header_data = protocol.receive_exact(sock, 14)
            _, _, msg_type, payload_len = struct.unpack('!8sBBI', header_data)
            payload_data = protocol.receive_exact(sock, payload_len)
            msg = protocol.Message(msg_type, payload_data)
            response = protocol.TransferResponse.from_message(msg)
            
            if response.accepted:
                self.transfer_id = response.transfer_id
                logger.info(f"✅ Transfer accepted: {self.transfer_id[:8]}...")
                sock.close()
                return True
            else:
                logger.error(f"❌ Transfer rejected: {response.reason}")
                sock.close()
                return False
                
        except Exception as e:
            logger.error(f"Error sending transfer request: {e}")
            return False


def main():
    """Main entry point for DCI client."""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(
        description="DCI File Transfer Client with Dynamic RL Optimization"
    )
    parser.add_argument('server', help="Server hostname or IP address")
    parser.add_argument('file', type=Path, help="File to send")
    parser.add_argument('--port', type=int, default=config.DEFAULT_SERVER_PORT,
                       help="Server port (default: 9876)")
    parser.add_argument('--streams', type=int, default=None,
                       help="Initial number of streams (default: RL decides)")
    parser.add_argument('--no-rl', action='store_true',
                       help="Disable RL acceleration")
    parser.add_argument('--algorithm', choices=['qlearning', 'ppo'], default='ppo',
                       help="RL algorithm to use (default: ppo)")
    
    args = parser.parse_args()
    
    # Override RL settings if requested
    if args.no_rl:
        config.RL_ENABLED = False
    
    # Override algorithm if specified
    if args.algorithm:
        config.RL_ALGORITHM = args.algorithm
    
    # Create client and send file
    client = DCIClient(server_host=args.server, server_port=args.port)
    success = client.send_file(filepath=args.file, num_streams=args.streams)
    
    if success:
        logger.info("🎉 Transfer successful")
        return 0
    else:
        logger.error("💥 Transfer failed")
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())

