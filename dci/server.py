"""
DCI Server Module - PERFORMANCE OPTIMIZED

Fixed: Deadlock removed while maintaining high throughput with buffering.
"""

import socket
import threading
import logging
import uuid
import time
import struct
from pathlib import Path
from typing import Dict, Set
from dataclasses import dataclass, field

from . import config
from . import protocol

logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)
logger = logging.getLogger(__name__)


@dataclass
class TransferState:
    transfer_id: str
    filename: str
    filesize: int
    checksum: str
    num_streams: int
    output_path: Path
    received_bytes: int = 0
    active_streams: Set[int] = field(default_factory=set)
    start_time: float = field(default_factory=time.time)
    file_handle: object = None
    finalized: bool = False
    write_lock: threading.Lock = field(default_factory=threading.Lock)  # ← NEW: Separate lock just for writes

    def is_complete(self) -> bool:
        return self.received_bytes >= self.filesize


class DCIServer:
    def __init__(
        self,
        host: str = config.DEFAULT_SERVER_HOST,
        port: int = config.DEFAULT_SERVER_PORT,
        storage_dir: Path = None,
    ):
        self.host = host
        self.port = port
        self.storage_dir = storage_dir or (config.TRANSFER_ROOT / "incoming")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.server_socket = None
        self.running = False
        self.transfers: Dict[str, TransferState] = {}
        self.transfers_lock = threading.Lock()

    def start(self):
        config.initialize_directories()
        
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(config.MAX_CONNECTIONS)
        self.running = True

        logger.info(f"🚀 DCI Server started on {self.host}:{self.port}")
        logger.info(f"📁 Storage directory: {self.storage_dir}")

        try:
            while self.running:
                try:
                    client_sock, client_addr = self.server_socket.accept()
                    
                    client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    client_sock.settimeout(60.0)
                    
                    threading.Thread(
                        target=self._handle_connection,
                        args=(client_sock, client_addr),
                        daemon=True,
                    ).start()
                except OSError as e:
                    if self.running:
                        logger.error(f"Accept error: {e}")
        finally:
            self.stop()

    def stop(self):
        logger.info("🛑 Shutting down server...")
        self.running = False
        
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass

        with self.transfers_lock:
            for transfer in list(self.transfers.values()):
                if transfer.file_handle:
                    try:
                        transfer.file_handle.close()
                    except:
                        pass
        
        logger.info("✅ DCI Server stopped")

    def _handle_connection(self, client_sock: socket.socket, client_addr):
        try:
            while True:
                try:
                    header = protocol.receive_exact(client_sock, 14)
                    _, _, msg_type, payload_len = struct.unpack("!8sBBI", header)
                    
                    payload = protocol.receive_exact(client_sock, payload_len)
                    msg = protocol.Message(msg_type, payload)

                    if msg.msg_type == protocol.MSG_TRANSFER_REQUEST:
                        self._handle_transfer_request(client_sock, msg)
                    elif msg.msg_type == protocol.MSG_CHUNK_DATA:
                        self._handle_chunk_data(client_sock, msg)

                except socket.timeout:
                    break
                except ConnectionError:
                    break

        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
        finally:
            try:
                client_sock.close()
            except:
                pass

    def _handle_transfer_request(self, client_sock: socket.socket, msg: protocol.Message):
        request = protocol.TransferRequest.from_message(msg)
        
        logger.info(
            f"📥 Transfer request: {request.filename} "
            f"({request.filesize} bytes, {request.num_streams} streams)"
        )

        transfer_id = str(uuid.uuid4())
        timestamp = int(time.time())
        base_name = Path(request.filename).stem
        extension = Path(request.filename).suffix
        unique_filename = f"{base_name}_{timestamp}_{transfer_id[:8]}{extension}"
        output_path = self.storage_dir / unique_filename

        try:
            transfer = TransferState(
                transfer_id=transfer_id,
                filename=request.filename,
                filesize=request.filesize,
                checksum=request.checksum,
                num_streams=request.num_streams,
                output_path=output_path,
            )

            # ✅ CORRECT: 16MB buffer for high throughput
            transfer.file_handle = open(output_path, "wb", buffering=16*1024*1024)
            
            with self.transfers_lock:
                self.transfers[transfer_id] = transfer

            response = protocol.TransferResponse(
                accepted=True, transfer_id=transfer_id, reason="Accepted"
            )
            client_sock.sendall(response.to_message().serialize())
            
            logger.info(f"✅ Transfer {transfer_id[:8]} accepted")

        except Exception as e:
            logger.error(f"Failed to create transfer: {e}")
            response = protocol.TransferResponse(
                accepted=False, transfer_id="", reason=str(e)
            )
            client_sock.sendall(response.to_message().serialize())

    def _handle_chunk_data(self, client_sock: socket.socket, msg: protocol.Message):
        chunk = protocol.ChunkData.from_message(msg)

        # Get transfer reference (fast, no lock needed)
        with self.transfers_lock:
            transfer = self.transfers.get(chunk.transfer_id)
        
        if not transfer or transfer.finalized:
            return

        # ✅ CRITICAL FIX: Use dedicated write_lock (not transfer-wide lock)
        # This allows ACK to be sent while writes are happening
        with transfer.write_lock:
            try:
                transfer.file_handle.seek(chunk.offset)
                transfer.file_handle.write(chunk.data)
                transfer.received_bytes += len(chunk.data)
                transfer.active_streams.add(chunk.stream_id)
                
            except Exception as e:
                logger.error(f"Write error: {e}")
                # Send ACK even on error to prevent client timeout
                ack = protocol.Message(protocol.MSG_ACK, b"")
                try:
                    client_sock.sendall(ack.serialize())
                except:
                    pass
                return

        # Progress logging (outside lock!)
        if transfer.received_bytes % (50 * 1024 * 1024) < len(chunk.data):
            progress = (transfer.received_bytes / transfer.filesize) * 100
            elapsed = time.time() - transfer.start_time
            if elapsed > 0:
                throughput = (transfer.received_bytes / elapsed) / (1024 * 1024)
                logger.info(
                    f"📈 Transfer {transfer.transfer_id[:8]}: {progress:.1f}% "
                    f"({throughput:.2f} MB/s, {len(transfer.active_streams)} streams)"
                )

        # Check completion (outside lock!)
        if transfer.is_complete() and not transfer.finalized:
            transfer.finalized = True
            threading.Thread(
                target=self._finalize_transfer,
                args=(transfer,),
                daemon=True
            ).start()

        # ✅ CRITICAL: Send ACK immediately after write completes (no lock!)
        ack = protocol.Message(protocol.MSG_ACK, b"")
        try:
            client_sock.sendall(ack.serialize())
        except:
            pass

    def _finalize_transfer(self, transfer: TransferState):
        try:
            # Wait for any in-flight writes
            with transfer.write_lock:
                transfer.file_handle.flush()
                transfer.file_handle.close()
                transfer.file_handle = None

            elapsed = time.time() - transfer.start_time
            throughput = (transfer.filesize / elapsed) / (1024 * 1024)

            logger.info("=" * 60)
            logger.info(f"✅ Transfer {transfer.transfer_id[:8]} complete")
            logger.info(f"   File: {transfer.filename}")
            logger.info(f"   Size: {transfer.filesize} bytes")
            logger.info(f"   Time: {elapsed:.2f}s")
            logger.info(f"   Throughput: {throughput:.2f} MB/s")
            logger.info(f"   Streams used: {len(transfer.active_streams)}")

            # Verify checksum
            computed_checksum = protocol.compute_file_checksum(transfer.output_path)
            
            if computed_checksum == transfer.checksum:
                final_path = config.TRANSFER_ROOT / "completed" / transfer.filename
                if final_path.exists():
                    timestamp = int(time.time())
                    final_path = config.TRANSFER_ROOT / "completed" / f"{Path(transfer.filename).stem}_{timestamp}{Path(transfer.filename).suffix}"
                
                transfer.output_path.rename(final_path)
                logger.info(f"✅ Checksum verified")
            else:
                failed_path = config.TRANSFER_ROOT / "failed" / transfer.filename
                transfer.output_path.rename(failed_path)
                logger.error(f"❌ Checksum FAILED")
            
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"❌ Finalization error: {e}", exc_info=True)
        finally:
            with self.transfers_lock:
                if transfer.transfer_id in self.transfers:
                    del self.transfers[transfer.transfer_id]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="DCI File Transfer Server")
    parser.add_argument("--host", default=config.DEFAULT_SERVER_HOST)
    parser.add_argument("--port", type=int, default=config.DEFAULT_SERVER_PORT)
    parser.add_argument("--storage", type=Path, default=None)
    args = parser.parse_args()

    server = DCIServer(host=args.host, port=args.port, storage_dir=args.storage)
    
    try:
        server.start()
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down...")
        server.stop()


if __name__ == "__main__":
    main()

