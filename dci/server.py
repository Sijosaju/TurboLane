"""
DCI Server Module
TCP-based file transfer server with parallel connection support.
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
    lock: threading.Lock = field(default_factory=threading.Lock)

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
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(config.MAX_CONNECTIONS)

        self.running = True
        logger.info(f"DCI Server started on {self.host}:{self.port}")
        logger.info(f"Storage directory: {self.storage_dir}")

        try:
            while self.running:
                client_sock, client_addr = self.server_socket.accept()
                logger.info(f"Connection from {client_addr}")

                threading.Thread(
                    target=self._handle_connection,
                    args=(client_sock, client_addr),
                    daemon=True,
                ).start()
        finally:
            self.stop()

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()

        with self.transfers_lock:
            for t in self.transfers.values():
                if t.file_handle:
                    t.file_handle.close()

        logger.info("DCI Server stopped")

    def _handle_connection(self, client_sock: socket.socket, client_addr):
        """
        IMPORTANT FIX:
        Keep socket OPEN and handle MULTIPLE messages.
        """
        try:
            while True:
                # Read header
                header = protocol.receive_exact(client_sock, 14)
                _, _, msg_type, payload_len = struct.unpack("!8sBBI", header)

                # Read payload
                payload = protocol.receive_exact(client_sock, payload_len)
                msg = protocol.Message(msg_type, payload)

                if msg.msg_type == protocol.MSG_TRANSFER_REQUEST:
                    self._handle_transfer_request(client_sock, msg)

                elif msg.msg_type == protocol.MSG_CHUNK_DATA:
                    self._handle_chunk_data(client_sock, msg)

                else:
                    logger.warning(f"Unknown message type {msg.msg_type}")

        except ConnectionError:
            logger.info(f"Client disconnected: {client_addr}")
        except Exception as e:
            logger.error(f"Connection error from {client_addr}: {e}")
        finally:
            client_sock.close()

    def _handle_transfer_request(self, client_sock: socket.socket, msg: protocol.Message):
        request = protocol.TransferRequest.from_message(msg)

        logger.info(
            f"Transfer request: {request.filename} "
            f"({request.filesize} bytes, {request.num_streams} streams)"
        )

        transfer_id = str(uuid.uuid4())
        output_path = self.storage_dir / request.filename

        if output_path.exists():
            output_path = self.storage_dir / f"{output_path.stem}_{transfer_id[:8]}{output_path.suffix}"

        transfer = TransferState(
            transfer_id=transfer_id,
            filename=request.filename,
            filesize=request.filesize,
            checksum=request.checksum,
            num_streams=request.num_streams,
            output_path=output_path,
        )

        transfer.file_handle = open(output_path, "wb")

        with self.transfers_lock:
            self.transfers[transfer_id] = transfer

        response = protocol.TransferResponse(
            accepted=True, transfer_id=transfer_id, reason="Accepted"
        )
        client_sock.sendall(response.to_message().serialize())

        logger.info(f"Transfer {transfer_id[:8]} accepted")

    def _handle_chunk_data(self, client_sock: socket.socket, msg: protocol.Message):
        chunk = protocol.ChunkData.from_message(msg)

        with self.transfers_lock:
            transfer = self.transfers.get(chunk.transfer_id)

        if not transfer:
            logger.error(f"Unknown transfer ID {chunk.transfer_id}")
            return

        with transfer.lock:
            transfer.active_streams.add(chunk.stream_id)
            transfer.file_handle.seek(chunk.offset)
            transfer.file_handle.write(chunk.data)
            transfer.received_bytes += len(chunk.data)

            if transfer.received_bytes % (50 * 1024 * 1024) < len(chunk.data):
                progress = (transfer.received_bytes / transfer.filesize) * 100
                logger.info(
                    f"Transfer {transfer.transfer_id[:8]}: {progress:.1f}%"
                )

            if transfer.is_complete():
                self._finalize_transfer(transfer)

        # Chunk-level ACK
        ack = protocol.Message(protocol.MSG_TRANSFER_COMPLETE, b"")
        client_sock.sendall(ack.serialize())

    def _finalize_transfer(self, transfer: TransferState):
        transfer.file_handle.close()
        transfer.file_handle = None

        elapsed = time.time() - transfer.start_time
        throughput = (transfer.filesize / elapsed) / (1024 * 1024)

        logger.info(f"Transfer {transfer.transfer_id[:8]} complete")
        logger.info(f"  Size: {transfer.filesize} bytes")
        logger.info(f"  Time: {elapsed:.2f}s")
        logger.info(f"  Throughput: {throughput:.2f} MB/s")

        computed_checksum = protocol.compute_file_checksum(transfer.output_path)

        if computed_checksum == transfer.checksum:
            final_path = config.TRANSFER_ROOT / "completed" / transfer.filename
            transfer.output_path.rename(final_path)
            logger.info("Checksum verified")
        else:
            failed_path = config.TRANSFER_ROOT / "failed" / transfer.filename
            transfer.output_path.rename(failed_path)
            logger.error("Checksum FAILED")

        with self.transfers_lock:
            del self.transfers[transfer.transfer_id]


def main():
    server = DCIServer()
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
