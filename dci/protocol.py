"""
DCI Protocol Module
Binary protocol for efficient file transfer metadata exchange.
"""
import struct
import hashlib
import json
from pathlib import Path
from typing import Dict, Optional, Tuple


# Protocol constants
PROTOCOL_VERSION = 1
MAGIC_BYTES = b"DCIFILE\x01"
CHUNK_SIZE = 512 * 1024  # 512KB chunks

# Message types
MSG_TRANSFER_REQUEST = 0x01
MSG_TRANSFER_ACCEPT = 0x02
MSG_TRANSFER_REJECT = 0x03
MSG_CHUNK_DATA = 0x04
MSG_TRANSFER_COMPLETE = 0x05
MSG_TRANSFER_ERROR = 0x06


class ProtocolError(Exception):
    """Protocol-level errors."""
    pass


class Message:
    """Base message class for DCI protocol."""
    
    def __init__(self, msg_type: int, payload: bytes = b""):
        self.msg_type = msg_type
        self.payload = payload
    
    def serialize(self) -> bytes:
        """
        Serialize message to wire format.
        Format: [MAGIC(8)][VERSION(1)][TYPE(1)][LENGTH(4)][PAYLOAD(n)]
        """
        payload_len = len(self.payload)
        header = struct.pack(
            "!8sBBI",
            MAGIC_BYTES,
            PROTOCOL_VERSION,
            self.msg_type,
            payload_len
        )
        return header + self.payload
    
    @staticmethod
    def deserialize(data: bytes) -> 'Message':
        """Deserialize message from wire format."""
        if len(data) < 14:
            raise ProtocolError("Message too short")
        
        magic, version, msg_type, payload_len = struct.unpack("!8sBBI", data[:14])
        
        if magic != MAGIC_BYTES:
            raise ProtocolError("Invalid magic bytes")
        
        if version != PROTOCOL_VERSION:
            raise ProtocolError(f"Unsupported protocol version: {version}")
        
        payload = data[14:14+payload_len]
        if len(payload) != payload_len:
            raise ProtocolError("Incomplete payload")
        
        return Message(msg_type, payload)


class TransferRequest:
    """Transfer request message with file metadata."""
    
    def __init__(self, filename: str, filesize: int, checksum: str, num_streams: int = 1):
        self.filename = filename
        self.filesize = filesize
        self.checksum = checksum
        self.num_streams = num_streams
    
    def to_message(self) -> Message:
        """Convert to protocol message."""
        payload_dict = {
            "filename": self.filename,
            "filesize": self.filesize,
            "checksum": self.checksum,
            "num_streams": self.num_streams
        }
        payload = json.dumps(payload_dict).encode('utf-8')
        return Message(MSG_TRANSFER_REQUEST, payload)
    
    @staticmethod
    def from_message(msg: Message) -> 'TransferRequest':
        """Parse from protocol message."""
        if msg.msg_type != MSG_TRANSFER_REQUEST:
            raise ProtocolError("Not a transfer request message")
        
        payload_dict = json.loads(msg.payload.decode('utf-8'))
        return TransferRequest(
            filename=payload_dict["filename"],
            filesize=payload_dict["filesize"],
            checksum=payload_dict["checksum"],
            num_streams=payload_dict.get("num_streams", 1)
        )


class TransferResponse:
    """Transfer accept/reject response."""
    
    def __init__(self, accepted: bool, reason: str = "", transfer_id: str = ""):
        self.accepted = accepted
        self.reason = reason
        self.transfer_id = transfer_id
    
    def to_message(self) -> Message:
        """Convert to protocol message."""
        msg_type = MSG_TRANSFER_ACCEPT if self.accepted else MSG_TRANSFER_REJECT
        payload_dict = {
            "reason": self.reason,
            "transfer_id": self.transfer_id
        }
        payload = json.dumps(payload_dict).encode('utf-8')
        return Message(msg_type, payload)
    
    @staticmethod
    def from_message(msg: Message) -> 'TransferResponse':
        """Parse from protocol message."""
        if msg.msg_type not in [MSG_TRANSFER_ACCEPT, MSG_TRANSFER_REJECT]:
            raise ProtocolError("Not a transfer response message")
        
        payload_dict = json.loads(msg.payload.decode('utf-8'))
        return TransferResponse(
            accepted=(msg.msg_type == MSG_TRANSFER_ACCEPT),
            reason=payload_dict.get("reason", ""),
            transfer_id=payload_dict.get("transfer_id", "")
        )


class ChunkData:
    """Chunk data message for parallel streams."""
    
    def __init__(self, transfer_id: str, stream_id: int, offset: int, data: bytes):
        self.transfer_id = transfer_id
        self.stream_id = stream_id
        self.offset = offset
        self.data = data
    
    def to_message(self) -> Message:
        """Convert to protocol message."""
        # Header: transfer_id(36) + stream_id(4) + offset(8) + data_len(4)
        header = struct.pack(
            "!36sIQI",
            self.transfer_id.encode('utf-8').ljust(36, b'\x00'),
            self.stream_id,
            self.offset,
            len(self.data)
        )
        payload = header + self.data
        return Message(MSG_CHUNK_DATA, payload)
    
    @staticmethod
    def from_message(msg: Message) -> 'ChunkData':
        """Parse from protocol message."""
        if msg.msg_type != MSG_CHUNK_DATA:
            raise ProtocolError("Not a chunk data message")
        
        if len(msg.payload) < 52:
            raise ProtocolError("Chunk message too short")
        
        transfer_id, stream_id, offset, data_len = struct.unpack("!36sIQI", msg.payload[:52])
        transfer_id = transfer_id.decode('utf-8').rstrip('\x00')
        data = msg.payload[52:52+data_len]
        
        return ChunkData(transfer_id, stream_id, offset, data)


def compute_file_checksum(filepath: Path, algorithm: str = "sha256") -> str:
    """Compute file checksum."""
    hash_obj = hashlib.new(algorithm)
    with open(filepath, 'rb') as f:
        while chunk := f.read(CHUNK_SIZE):
            hash_obj.update(chunk)
    return hash_obj.hexdigest()


def receive_exact(sock, num_bytes: int) -> bytes:
    """Receive exactly num_bytes from socket."""
    data = b""
    while len(data) < num_bytes:
        chunk = sock.recv(num_bytes - len(data))
        if not chunk:
            raise ConnectionError("Socket closed during receive")
        data += chunk
    return data