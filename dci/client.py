"""
DCI Client Module
TCP-based file transfer client with RL-driven parallel streams.
"""
import socket
import threading
import logging
import time
import struct
from pathlib import Path
from typing import Optional
from queue import Queue, Empty
from dataclasses import dataclass

from . import config
from . import protocol

logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)
logger = logging.getLogger(__name__)

# Try to import RL components
try:
    from turbolane.modes.dci import DCIPolicy
    RL_AVAILABLE = True
except ImportError as e:
    logger.warning(f"RL components not available: {e}")
    RL_AVAILABLE = False


@dataclass
class StreamTask:
    """Task for individual stream worker."""
    stream_id: int
    offset: int
    size: int


class DCIClient:
    """DCI file transfer client with RL-based multi-streaming."""
    
    def __init__(self, server_host: str, server_port: int = config.DEFAULT_SERVER_PORT):
        self.server_host = server_host
        self.server_port = server_port
        self.transfer_id = None
        self.rl_enabled = config.RL_ENABLED and RL_AVAILABLE
        
        config.initialize_directories()
        
        if self.rl_enabled:
            self.rl_policy = DCIPolicy(model_path=config.get_model_path())
            logger.info("RL acceleration enabled")
        else:
            self.rl_policy = None
            logger.warning("RL acceleration disabled")
    
    def send_file(self, filepath: Path, num_streams: Optional[int] = None) -> bool:
        """Send file to server with RL-optimized parallel streams."""
        if not filepath.exists():
            logger.error(f"File not found: {filepath}")
            return False
        
        filesize = filepath.stat().st_size
        logger.info(f"Preparing to send: {filepath.name} ({filesize} bytes)")
        
        logger.info("Computing file checksum...")
        checksum = protocol.compute_file_checksum(filepath)
        logger.info(f"Checksum: {checksum}")
        
        # Determine number of streams
        if num_streams is None:
            if self.rl_enabled:
                num_streams = self.rl_policy.get_optimal_streams(filesize)
            else:
                num_streams = config.RL_INITIAL_STREAMS
        
        num_streams = max(config.RL_MIN_STREAMS, 
                         min(num_streams, config.RL_MAX_STREAMS))
        logger.info(f"Using {num_streams} parallel streams")
        
        if not self._send_transfer_request(filepath.name, filesize, checksum, num_streams):
            return False
        
        start_time = time.time()
        success = self._transfer_with_streams(filepath, filesize, num_streams)
        elapsed = time.time() - start_time
        
        if success:
            throughput = (filesize / elapsed) / (1024 * 1024)
            logger.info(f"Transfer complete!")
            logger.info(f"  Time: {elapsed:.2f}s")
            logger.info(f"  Throughput: {throughput:.2f} MB/s")
            
            if self.rl_enabled:
                self.rl_policy.update_performance(filesize, num_streams, throughput, elapsed)
                self.rl_policy.save()
        
        return success
    
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
            _, _, msg_type, payload_len = struct.unpack("!8sBBI", header_data)
            payload_data = protocol.receive_exact(sock, payload_len)
            msg = protocol.Message(msg_type, payload_data)
            
            response = protocol.TransferResponse.from_message(msg)
            
            if response.accepted:
                self.transfer_id = response.transfer_id
                logger.info(f"Transfer accepted: {self.transfer_id[:8]}")
                sock.close()
                return True
            else:
                logger.error(f"Transfer rejected: {response.reason}")
                sock.close()
                return False
                
        except Exception as e:
            logger.error(f"Error sending transfer request: {e}")
            return False
    
    def _transfer_with_streams(self, filepath: Path, filesize: int, 
                              num_streams: int) -> bool:
        """Transfer file using parallel streams."""
        try:
            chunk_size = config.CHUNK_SIZE
            task_queue = Queue()
            
            # Divide file into tasks
            offset = 0
            stream_id = 0
            while offset < filesize:
                size = min(chunk_size, filesize - offset)
                task_queue.put(StreamTask(stream_id % num_streams, offset, size))
                offset += size
                stream_id += 1
            
            logger.info(f"Created {task_queue.qsize()} transfer tasks")
            
            # Launch stream workers
            threads = []
            success_flags = [True] * num_streams
            
            for stream_id in range(num_streams):
                thread = threading.Thread(
                    target=self._stream_worker,
                    args=(filepath, task_queue, stream_id, success_flags),
                    daemon=True
                )
                thread.start()
                threads.append(thread)
            
            for thread in threads:
                thread.join()
            
            return all(success_flags)
            
        except Exception as e:
            logger.error(f"Transfer error: {e}")
            return False
    
    def _stream_worker(self, filepath: Path, task_queue: Queue, 
                      stream_id: int, success_flags: list):
        """Worker thread for individual stream."""
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((self.server_host, self.server_port))
            
            with open(filepath, 'rb') as f:
                while True:
                    try:
                        task = task_queue.get(timeout=1)
                    except Empty:
                        break
                    
                    f.seek(task.offset)
                    data = f.read(task.size)
                    
                    chunk = protocol.ChunkData(
                        transfer_id=self.transfer_id,
                        stream_id=stream_id,
                        offset=task.offset,
                        data=data
                    )
                    sock.sendall(chunk.to_message().serialize())
                    
                    try:
                        ack_header = protocol.receive_exact(sock, 14)
                        _, _, ack_type, ack_len = struct.unpack("!8sBBI", ack_header)
                        if ack_len > 0:
                            protocol.receive_exact(sock, ack_len)
                    except:
                        pass
                    
                    task_queue.task_done()
            
            logger.debug(f"Stream {stream_id} completed successfully")
            
        except Exception as e:
            logger.error(f"Stream {stream_id} error: {e}")
            success_flags[stream_id] = False
        finally:
            if sock:
                sock.close()


def main():
    """Main entry point for client."""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="DCI File Transfer Client")
    parser.add_argument("server", help="Server hostname or IP")
    parser.add_argument("file", type=Path, help="File to send")
    parser.add_argument("--port", type=int, default=config.DEFAULT_SERVER_PORT)
    parser.add_argument("--streams", type=int, default=None)
    parser.add_argument("--no-rl", action="store_true")
    
    args = parser.parse_args()
    
    if args.no_rl:
        config.RL_ENABLED = False
    
    client = DCIClient(server_host=args.server, server_port=args.port)
    success = client.send_file(filepath=args.file, num_streams=args.streams)
    
    if success:
        logger.info("Transfer successful")
        return 0
    else:
        logger.error("Transfer failed")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())