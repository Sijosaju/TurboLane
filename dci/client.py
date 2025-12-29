"""
DCI Client Module - ULTIMATE VERSION

Fully integrated with turbolane library for dynamic stream adjustment.
"""

import socket
import threading
import logging
import time
import struct
from pathlib import Path
from typing import Optional, List
from queue import Queue, Empty
from dataclasses import dataclass

from . import config
from . import protocol

# Configure logging
logging.basicConfig(
    level=config.LOG_LEVEL,
    format=config.LOG_FORMAT
)
logger = logging.getLogger(__name__)

# Import turbolane components
try:
    from turbolane.rl.agent import RLAgent
    from turbolane.rl.storage import QTableStorage
    RL_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Turbolane RL components not available: {e}")
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
                        sock.settimeout(30.0)  # 30 second timeout for final ACKs
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
    
    This is the ULTIMATE version that:
    - Uses turbolane.rl.agent.RLAgent for decisions
    - Uses turbolane.rl.storage.QTableStorage for persistence
    - Dynamically spawns/kills streams during transfer
    - Learns from every transfer to improve future performance
    """

    def __init__(self, server_host: str, server_port: int = config.DEFAULT_SERVER_PORT):
        self.server_host = server_host
        self.server_port = server_port
        self.transfer_id = None
        self.transfer_complete = False
        self.rl_enabled = config.RL_ENABLED and RL_AVAILABLE

        # Initialize directories
        config.initialize_directories()

        if self.rl_enabled:
            # Initialize RL agent from turbolane library
            self.storage = QTableStorage(storage_path=config.get_model_path())
            
            # Load existing Q-table
            Q, metadata = self.storage.load()
            
            # Create RL agent
            self.rl_agent = RLAgent(
                monitoring_interval=5.0,  # Check every 5 seconds
                min_connections=config.RL_MIN_STREAMS,
                max_connections=config.RL_MAX_STREAMS,
                default_connections=config.RL_INITIAL_STREAMS
            )
            
            # Restore Q-table if exists
            if Q:
                self.rl_agent.Q = Q
                self.rl_agent.total_decisions = metadata.get('total_decisions', 0)
                self.rl_agent.total_learning_updates = metadata.get('total_updates', 0)
                logger.info(f"✅ Loaded Q-table: {len(Q)} states, "
                           f"{metadata.get('total_decisions', 0)} decisions")
            
            logger.info("🚀 RL acceleration enabled (turbolane integration)")
            logger.info(f"   Model path: {config.get_model_path()}")
        else:
            self.rl_agent = None
            self.storage = None
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
                num_streams = self.rl_agent.current_connections
            else:
                num_streams = config.RL_INITIAL_STREAMS

        num_streams = max(config.RL_MIN_STREAMS, min(num_streams, config.RL_MAX_STREAMS))
        
        if self.rl_enabled:
            self.rl_agent.current_connections = num_streams

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
            logger.info("=" * 60)

            # Save Q-table to disk
            if self.rl_enabled:
                stats = self.rl_agent.get_stats()
                self.storage.save(self.rl_agent.Q, stats)
                logger.info(f"💾 Q-table saved: {len(self.rl_agent.Q)} states")
        else:
            logger.error("❌ Transfer failed")

        return success

    def adaptive_monitor(self, total_filesize: int):
        """
        Monitor thread that uses turbolane.rl.agent to make adaptive decisions.
        This is where the magic happens - streams are adjusted in real-time!
        """
        logger.info("🔍 Starting adaptive monitoring with turbolane RL agent...")

        while not self.stop_monitoring.is_set():
            time.sleep(5)  # Monitor every 5 seconds

            if self.transfer_complete:
                logger.info("✅ Transfer complete - freezing RL decisions")
                break

            if self.stop_monitoring.is_set():
                break

            with self.metrics.lock:
                current_time = time.time()
                time_delta = current_time - self.metrics.last_measurement_time

                if time_delta < 1.0:
                    continue  # Too soon to measure accurately

                bytes_delta = self.metrics.bytes_sent - self.metrics.last_measurement_bytes
                throughput_mbps = (bytes_delta / time_delta) / (1024 * 1024)
                self.metrics.current_throughput_mbps = throughput_mbps

                # Calculate progress
                progress = (self.metrics.bytes_sent / total_filesize) * 100
                current_streams = self.worker_pool.get_active_count()

                logger.info(f"📈 Progress: {progress:.1f}% | "
                           f"Throughput: {throughput_mbps:.2f} MB/s | "
                           f"Active streams: {current_streams}")

                # Estimate RTT and loss (since we don't have real metrics in DCI)
                estimated_rtt = 50.0  # Assume datacenter link
                estimated_loss = 0.1 if throughput_mbps > 100 else 0.5

                # ⚡ STEP 1: Make RL decision
                desired_streams = self.rl_agent.make_decision(
                    throughput_mbps,    # throughput in Mbps
                    estimated_rtt,      # rtt in ms
                    estimated_loss      # packet_loss_pct (percentage)
                )
                # Note: agent.py expects positional args (throughput, rtt, packet_loss_pct)

                # Adjust worker pool based on RL decision
                stream_diff = desired_streams - current_streams
                if stream_diff > 0:
                    # Need more streams
                    logger.info(f"🔧 RL Decision: SCALE UP by {stream_diff} streams "
                               f"({current_streams} → {desired_streams})")
                    self.worker_pool.spawn_workers(stream_diff)
                elif stream_diff < 0:
                    # Need fewer streams
                    logger.info(f"🔧 RL Decision: SCALE DOWN by {-stream_diff} streams "
                               f"({current_streams} → {desired_streams})")
                    self.worker_pool.kill_workers(-stream_diff)
                else:
                    logger.debug(f"🔧 RL Decision: MAINTAIN {current_streams} streams")

                # ⚡ STEP 2: Learn from feedback (CRITICAL - THIS WAS MISSING!)
                self.rl_agent.learn_from_feedback(
                    throughput_mbps,    # current_throughput
                    estimated_rtt,      # current_rtt
                    estimated_loss      # current_packet_loss_pct
                )
                # Note: agent.py expects positional args

                # Update measurement baseline
                self.metrics.last_measurement_time = current_time
                self.metrics.last_measurement_bytes = self.metrics.bytes_sent

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

    args = parser.parse_args()

    # Override RL setting if requested
    if args.no_rl:
        config.RL_ENABLED = False

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
