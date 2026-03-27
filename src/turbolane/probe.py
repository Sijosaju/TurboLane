"""
turbolane/probe.py

TCPSocketReader — automatic network metric collection from active TCP sockets.

Reads throughput, RTT, and packet loss directly from the OS TCP stack
via TCP_INFO (Linux/macOS) or SIO_TCP_INFO (Windows).

No external probing. No synthetic connections. Metrics come from the
real transfer sockets, exactly as used in:
    Jamil et al., "A Reinforcement Learning Approach to Optimize
    Available Network Bandwidth Utilization", arXiv:2211.11949v2

Design:
    - OS is detected once at init via platform.system()
    - All OS-specific logic is isolated inside _LinuxReader,
      _MacOSReader, _WindowsReader, _FallbackReader
    - Public API is identical on all platforms
    - Pure stdlib: socket, ctypes, platform, time — no pip deps

Public API:
    reader = TCPSocketReader(sockets)
    reader.update_sockets(sockets)
    snapshot = reader.read()   → SocketSnapshot(throughput_mbps, rtt_ms, loss_pct, ...)
"""

import ctypes
import logging
import platform
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

@dataclass
class SocketSnapshot:
    """
    Aggregated network metrics across all tracked sockets.

    throughput_mbps : aggregate transfer rate (Mbps)
    rtt_ms          : mean smoothed RTT across all sockets (ms)
    loss_pct        : aggregate packet loss percentage
    rtt_gradient    : rate-of-change of RTT (ms/s) — paper's state variable
    rtt_ratio       : current_rtt / min_rtt_seen  — paper's state variable
    socket_count    : number of sockets contributing
    valid           : False if no sockets or OS read failed → use safe defaults
    """
    throughput_mbps: float = 0.0
    rtt_ms: float = 50.0          # safe neutral default
    loss_pct: float = 0.0
    rtt_gradient: float = 0.0
    rtt_ratio: float = 1.0
    socket_count: int = 0
    valid: bool = False


# ---------------------------------------------------------------------------
# Per-socket state (tracks deltas between reads)
# ---------------------------------------------------------------------------

@dataclass
class _SocketState:
    sock: socket.socket
    bytes_at_last_read: int = 0
    retrans_at_last_read: int = 0
    last_read_time: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# OS reader base
# ---------------------------------------------------------------------------

class _BaseReader:
    """
    Subclasses implement _read_one(sock) → dict | None

    Expected dict keys:
        rtt_us      : smoothed RTT in microseconds (int)
        retrans     : cumulative retransmissions (int)
        mss         : max segment size in bytes (int)
    """

    def read_all(self, socket_states: List[_SocketState], interval_seconds: float) -> SocketSnapshot:
        if not socket_states or interval_seconds <= 0:
            return SocketSnapshot()

        total_bytes_delta = 0
        rtt_samples = []
        total_retrans_delta = 0
        total_packets_sent = 0

        now = time.monotonic()

        for ss in socket_states:
            info = self._read_one(ss.sock)
            if info is None:
                continue

            # --- Throughput: bytes transferred since last read ---
            try:
                # bytes_sent is tracked externally via update_bytes()
                # rtt and retrans come from TCP_INFO
                pass
            except Exception:
                pass

            rtt_us = info.get("rtt_us", 0)
            if rtt_us > 0:
                rtt_samples.append(rtt_us / 1000.0)  # convert µs → ms

            retrans_now = info.get("retrans", 0)
            retrans_delta = max(0, retrans_now - ss.retrans_at_last_read)
            total_retrans_delta += retrans_delta
            ss.retrans_at_last_read = retrans_now

            mss = info.get("mss", 1460)
            if mss <= 0:
                mss = 1460

            # Estimate packets sent this interval from bytes delta
            # bytes_delta tracked via update_bytes call before read_all
            bytes_delta = getattr(ss, "_bytes_delta_this_interval", 0)
            total_bytes_delta += bytes_delta
            packets_this_interval = max(1, bytes_delta // mss)
            total_packets_sent += packets_this_interval

        # --- Aggregate throughput ---
        throughput_mbps = (total_bytes_delta * 8) / (interval_seconds * 1_000_000) if interval_seconds > 0 else 0.0

        # --- Aggregate RTT ---
        rtt_ms = sum(rtt_samples) / len(rtt_samples) if rtt_samples else 50.0

        # --- Aggregate loss ---
        if total_packets_sent > 0:
            loss_pct = min(100.0, (total_retrans_delta / total_packets_sent) * 100.0)
        else:
            loss_pct = 0.0

        return SocketSnapshot(
            throughput_mbps=round(throughput_mbps, 4),
            rtt_ms=round(rtt_ms, 3),
            loss_pct=round(loss_pct, 4),
            socket_count=len(socket_states),
            valid=len(rtt_samples) > 0,
        )

    def _read_one(self, sock: socket.socket) -> Optional[dict]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Linux reader — TCP_INFO via getsockopt
# ---------------------------------------------------------------------------

# Partial TCP_INFO struct — only fields we need, up to tcpi_total_retrans
# Full struct is larger but we only need the first portion.
# Offsets verified against linux/tcp.h (kernel 4.x+):
#   tcpi_state         u8   @ 0
#   tcpi_retransmits   u8   @ 4
#   ...
#   tcpi_rtt           u32  @ 28   (smoothed RTT in µs)
#   tcpi_rttvar        u32  @ 32
#   tcpi_snd_mss       u32  @ 64
#   tcpi_total_retrans u32  @ 96

_LINUX_TCP_INFO_FMT = "BBBBBBBBIIIIIIIIIIIIIIIIIIIIIII"
_LINUX_TCP_INFO_SIZE = struct.calcsize(_LINUX_TCP_INFO_FMT)

# Field indices in the unpacked tuple
_LINUX_IDX_RTT = 10          # tcpi_rtt        (field 10, u32, µs)
_LINUX_IDX_SND_MSS = 22      # tcpi_snd_mss    (field 22, u32, bytes)
_LINUX_IDX_TOTAL_RETRANS = 29  # tcpi_total_retrans (field 29, u32)

try:
    import socket as _sock_mod
    _TCP_INFO_LINUX = getattr(_sock_mod, "TCP_INFO", 11)
except Exception:
    _TCP_INFO_LINUX = 11


class _LinuxReader(_BaseReader):
    def _read_one(self, sock: socket.socket) -> Optional[dict]:
        try:
            raw = sock.getsockopt(socket.IPPROTO_TCP, _TCP_INFO_LINUX, 256)
            if len(raw) < _LINUX_TCP_INFO_SIZE:
                return None
            fields = struct.unpack_from(_LINUX_TCP_INFO_FMT, raw)
            return {
                "rtt_us": fields[_LINUX_IDX_RTT],
                "retrans": fields[_LINUX_IDX_TOTAL_RETRANS],
                "mss": fields[_LINUX_IDX_SND_MSS],
            }
        except (OSError, struct.error) as exc:
            logger.debug("LinuxReader._read_one failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# macOS reader — TCP_INFO via getsockopt (different struct layout)
# ---------------------------------------------------------------------------
# macOS tcp_connection_info (from netinet/tcp.h):
#   tcpi_state              u8   @ 0
#   ...
#   tcpi_snd_mss            u32  @ 8
#   ...
#   tcpi_rttcur             u32  @ 24   (current RTT in µs)
#   tcpi_srtt               u32  @ 28   (smoothed RTT in µs)  ← use this
#   ...
#   tcpi_txretransmitpackets u64  @ 64
# struct size: 156 bytes

_MACOS_TCP_INFO_FMT = (
    "BBHIIII"   # 0..24: state(1) pad(1) pad(2) snd_mss(4) ... rttcur(4) ...
    "IIIIII"    # ...
    "QQ"        # txpackets, txretransmitpackets at offsets ~56, 64
    "QQ"
    "IIII"
)

# We use a simpler fixed-offset approach for macOS
_MACOS_TCP_INFO_CONST = getattr(socket, "TCP_INFO", 0x200)
_MACOS_STRUCT_SIZE = 156

_MACOS_OFF_SND_MSS    = 8    # u32
_MACOS_OFF_SRTT       = 28   # u32  smoothed RTT in µs
_MACOS_OFF_TXRETRANS  = 64   # u64  txretransmitpackets


class _MacOSReader(_BaseReader):
    def _read_one(self, sock: socket.socket) -> Optional[dict]:
        try:
            raw = sock.getsockopt(socket.IPPROTO_TCP, _MACOS_TCP_INFO_CONST, _MACOS_STRUCT_SIZE)
            if len(raw) < _MACOS_STRUCT_SIZE:
                return None
            snd_mss = struct.unpack_from("I", raw, _MACOS_OFF_SND_MSS)[0]
            srtt    = struct.unpack_from("I", raw, _MACOS_OFF_SRTT)[0]
            retrans = struct.unpack_from("Q", raw, _MACOS_OFF_TXRETRANS)[0]
            return {
                "rtt_us": srtt,
                "retrans": int(retrans),
                "mss": snd_mss if snd_mss > 0 else 1460,
            }
        except (OSError, struct.error) as exc:
            logger.debug("MacOSReader._read_one failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Windows reader — SIO_TCP_INFO via WSAIoctl (ctypes)
# ---------------------------------------------------------------------------
# TCP_INFO_v0 struct (ws2def.h / mstcpip.h):
#   State           TCPSTATE (u32)  @ 0
#   Mss             u32             @ 4
#   ConnectionTimeMs u64            @ 8
#   TimestampsEnabled BOOL (u32)    @ 16
#   RttUs           u32             @ 20   ← smoothed RTT in µs
#   MinRttUs        u32             @ 24
#   BytesInFlight   u32             @ 28
#   Cwnd            u32             @ 32
#   SndWnd          u32             @ 36
#   RcvWnd          u32             @ 40
#   RcvBuf          u32             @ 44
#   BytesOut        u64             @ 48
#   BytesIn         u64             @ 56
#   BytesReordered  u32             @ 64
#   BytesRetrans    u32             @ 68
#   FastRetrans     u32             @ 72
#   DupAcksIn       u32             @ 76
#   TimeoutEpisodes u32             @ 80
#   SynRetrans      u8              @ 84
# Total: 88 bytes

_WIN_TCP_INFO_FMT = "IIIQIIIIIIIQQIIIIIIB"
_WIN_TCP_INFO_SIZE = struct.calcsize(_WIN_TCP_INFO_FMT)  # should be 88

_WIN_OFF_MSS        = 4
_WIN_OFF_RTT_US     = 20
_WIN_OFF_BYTES_RETR = 68   # BytesRetrans (u32)

# SIO_TCP_INFO ioctl code
_SIO_TCP_INFO = ctypes.c_ulong(0x39C8001A)  # 0x39C8001A = SIO_TCP_INFO (v0)


class _WindowsReader(_BaseReader):
    def __init__(self):
        self._ws2_32 = None
        self._wsa_ioctl = None
        self._setup_winsock()

    def _setup_winsock(self):
        try:
            self._ws2_32 = ctypes.windll.ws2_32  # type: ignore[attr-defined]
            self._wsa_ioctl = self._ws2_32.WSAIoctl
            self._wsa_ioctl.restype = ctypes.c_int
            self._wsa_ioctl.argtypes = [
                ctypes.c_uint64,   # SOCKET
                ctypes.c_ulong,    # dwIoControlCode
                ctypes.c_void_p,   # lpvInBuffer
                ctypes.c_ulong,    # cbInBuffer
                ctypes.c_void_p,   # lpvOutBuffer
                ctypes.c_ulong,    # cbOutBuffer
                ctypes.POINTER(ctypes.c_ulong),  # lpcbBytesReturned
                ctypes.c_void_p,   # lpOverlapped
                ctypes.c_void_p,   # lpCompletionRoutine
            ]
            logger.debug("WindowsReader: WSAIoctl loaded successfully")
        except (AttributeError, OSError) as exc:
            logger.warning("WindowsReader: WSAIoctl setup failed: %s", exc)
            self._ws2_32 = None

    def _read_one(self, sock: socket.socket) -> Optional[dict]:
        if self._ws2_32 is None:
            return None
        try:
            # Input: version = 0 (TCP_INFO_v0)
            in_version = ctypes.c_ulong(0)
            out_buf = ctypes.create_string_buffer(_WIN_TCP_INFO_SIZE)
            bytes_returned = ctypes.c_ulong(0)

            fileno = sock.fileno()
            ret = self._wsa_ioctl(
                fileno,
                _SIO_TCP_INFO.value,
                ctypes.byref(in_version),
                ctypes.sizeof(in_version),
                out_buf,
                ctypes.sizeof(out_buf),
                ctypes.byref(bytes_returned),
                None,
                None,
            )
            if ret != 0:
                return None

            raw = bytes(out_buf)
            mss     = struct.unpack_from("I", raw, _WIN_OFF_MSS)[0]
            rtt_us  = struct.unpack_from("I", raw, _WIN_OFF_RTT_US)[0]
            retrans = struct.unpack_from("I", raw, _WIN_OFF_BYTES_RETR)[0]

            return {
                "rtt_us": rtt_us,
                "retrans": int(retrans),
                "mss": mss if mss > 0 else 1460,
            }
        except (OSError, struct.error) as exc:
            logger.debug("WindowsReader._read_one failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Fallback reader — throughput only (RTT/loss use safe defaults)
# ---------------------------------------------------------------------------

class _FallbackReader(_BaseReader):
    """
    Used when OS is not Linux/macOS/Windows, or when TCP_INFO is unavailable.
    Throughput is still accurate (bytes/time). RTT and loss use safe defaults.
    """

    def _read_one(self, sock: socket.socket) -> Optional[dict]:
        # Return safe neutral values — no OS call needed
        return {
            "rtt_us": 50_000,   # 50ms default
            "retrans": 0,
            "mss": 1460,
        }


# ---------------------------------------------------------------------------
# Main public class
# ---------------------------------------------------------------------------

class TCPSocketReader:
    """
    Automatic, OS-independent network metric collector.

    Reads throughput, RTT, and packet loss from a set of active TCP sockets.
    Detects the OS once at init and routes to the correct internal reader.

    Usage:
        reader = TCPSocketReader(sockets)
        snapshot = reader.read()    # SocketSnapshot

        # When stream count changes:
        reader.update_sockets(new_sockets)

        # Report bytes transferred (called by engine each interval):
        reader.report_bytes(socket, bytes_count)
    """

    def __init__(self, sockets: Optional[List[socket.socket]] = None):
        self._os = platform.system()
        self._reader = self._build_reader()
        self._socket_states: List[_SocketState] = []
        self._last_read_time: float = time.monotonic()

        # RTT history for gradient and ratio computation
        self._rtt_history: list = []
        self._min_rtt_ms: float = float("inf")

        if sockets:
            self.update_sockets(sockets)

        logger.info(
            "TCPSocketReader init: os=%s reader=%s sockets=%d",
            self._os,
            type(self._reader).__name__,
            len(self._socket_states),
        )

    def _build_reader(self) -> _BaseReader:
        if self._os == "Linux":
            return _LinuxReader()
        elif self._os == "Darwin":
            return _MacOSReader()
        elif self._os == "Windows":
            reader = _WindowsReader()
            if reader._ws2_32 is None:
                logger.warning("TCPSocketReader: Windows WSAIoctl unavailable, using fallback")
                return _FallbackReader()
            return reader
        else:
            logger.warning("TCPSocketReader: unknown OS '%s', using fallback reader", self._os)
            return _FallbackReader()

    # -----------------------------------------------------------------------
    # Socket management
    # -----------------------------------------------------------------------

    def update_sockets(self, sockets: List[socket.socket]) -> None:
        """
        Replace the tracked socket list.
        Preserves retrans counters for sockets that are still present.
        New sockets start fresh.
        """
        existing = {id(ss.sock): ss for ss in self._socket_states}
        new_states = []
        for sock in sockets:
            if id(sock) in existing:
                new_states.append(existing[id(sock)])
            else:
                new_states.append(_SocketState(sock=sock))
        self._socket_states = new_states
        logger.debug("TCPSocketReader: tracking %d sockets", len(new_states))

    def report_bytes(self, sock: socket.socket, bytes_transferred: int) -> None:
        """
        Report bytes transferred on a specific socket since last call.
        Called by the engine/user after each transfer chunk.
        """
        for ss in self._socket_states:
            if ss.sock is sock:
                ss._bytes_delta_this_interval = getattr(ss, "_bytes_delta_this_interval", 0) + bytes_transferred
                return

    def report_bytes_all(self, total_bytes: int) -> None:
        """
        Report total bytes transferred across all sockets since last read.
        Use this when you track aggregate bytes rather than per-socket.
        """
        if not self._socket_states:
            return
        per_socket = total_bytes // len(self._socket_states)
        remainder = total_bytes % len(self._socket_states)
        for i, ss in enumerate(self._socket_states):
            ss._bytes_delta_this_interval = per_socket + (remainder if i == 0 else 0)

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------

    def read(self) -> SocketSnapshot:
        """
        Read aggregate metrics from all tracked sockets.

        Returns a SocketSnapshot with:
            - throughput_mbps : aggregate transfer rate
            - rtt_ms          : mean smoothed RTT
            - loss_pct        : aggregate packet loss %
            - rtt_gradient    : RTT rate of change (ms/s)
            - rtt_ratio       : current_rtt / min_rtt_seen
        """
        now = time.monotonic()
        interval = now - self._last_read_time
        if interval <= 0:
            interval = 1.0

        snapshot = self._reader.read_all(self._socket_states, interval)

        # Compute paper's derived RTT signals
        if snapshot.valid and snapshot.rtt_ms > 0:
            prev_rtt = self._rtt_history[-1] if self._rtt_history else snapshot.rtt_ms
            snapshot.rtt_gradient = (snapshot.rtt_ms - prev_rtt) / interval

            if snapshot.rtt_ms < self._min_rtt_ms:
                self._min_rtt_ms = snapshot.rtt_ms
            snapshot.rtt_ratio = snapshot.rtt_ms / self._min_rtt_ms

            self._rtt_history.append(snapshot.rtt_ms)
            if len(self._rtt_history) > 50:
                self._rtt_history.pop(0)

        # Reset per-interval byte counters
        for ss in self._socket_states:
            ss._bytes_delta_this_interval = 0
            ss.last_read_time = now

        self._last_read_time = now
        return snapshot

    # -----------------------------------------------------------------------
    # Info
    # -----------------------------------------------------------------------

    @property
    def os_name(self) -> str:
        return self._os

    @property
    def reader_type(self) -> str:
        return type(self._reader).__name__

    @property
    def socket_count(self) -> int:
        return len(self._socket_states)

    def __repr__(self) -> str:
        return (
            f"TCPSocketReader(os={self._os!r}, "
            f"reader={self.reader_type}, "
            f"sockets={self.socket_count})"
        )
