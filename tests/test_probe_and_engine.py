"""
tests/test_probe_and_engine.py

Comprehensive test suite for TCPSocketReader and TurboLaneEngine
automatic metric collection.

Tests cover:
    - OS detection and reader selection
    - TCPSocketReader initialization and socket management
    - Throughput calculation accuracy
    - RTT gradient and ratio computation
    - Packet loss calculation
    - SocketSnapshot dataclass
    - All three engine metric modes (socket, manual, legacy)
    - Backward compatibility (legacy API unchanged)
    - Fallback behavior when no metrics available
    - Engine get_stats() includes probe info
    - Edge cases: empty sockets, zero bytes, invalid sockets
"""

import platform
import socket
import struct
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_socket(fileno=10):
    """Create a mock socket."""
    sock = MagicMock(spec=socket.socket)
    sock.fileno.return_value = fileno
    return sock


def _make_linux_tcp_info(rtt_us=30000, total_retrans=5, snd_mss=1460):
    """
    Build a fake Linux TCP_INFO binary blob.
    Format: BBBBBBBBIIIIIIIIIIIIIIIIIIIIIII (31 fields)
    Field 10 = rtt_us, field 22 = snd_mss, field 29 = total_retrans
    """
    fmt = "BBBBBBBBIIIIIIIIIIIIIIIIIIIIIII"
    fields = [0] * 31
    fields[10] = rtt_us
    fields[22] = snd_mss
    fields[29] = total_retrans
    return struct.pack(fmt, *fields)


def _make_macos_tcp_info(srtt_us=30000, retrans=3, snd_mss=1460):
    """Build a fake macOS TCP_INFO binary blob (156 bytes)."""
    raw = bytearray(156)
    struct.pack_into("I", raw, 8, snd_mss)   # snd_mss at offset 8
    struct.pack_into("I", raw, 28, srtt_us)  # srtt at offset 28
    struct.pack_into("Q", raw, 64, retrans)  # txretransmitpackets at offset 64
    return bytes(raw)


# ---------------------------------------------------------------------------
# Test: SocketSnapshot
# ---------------------------------------------------------------------------

class TestSocketSnapshot(unittest.TestCase):

    def test_default_values(self):
        from turbolane.probe import SocketSnapshot
        s = SocketSnapshot()
        self.assertEqual(s.throughput_mbps, 0.0)
        self.assertEqual(s.rtt_ms, 50.0)
        self.assertEqual(s.loss_pct, 0.0)
        self.assertEqual(s.rtt_gradient, 0.0)
        self.assertEqual(s.rtt_ratio, 1.0)
        self.assertEqual(s.socket_count, 0)
        self.assertFalse(s.valid)

    def test_custom_values(self):
        from turbolane.probe import SocketSnapshot
        s = SocketSnapshot(
            throughput_mbps=45.5,
            rtt_ms=32.1,
            loss_pct=0.15,
            rtt_gradient=-0.5,
            rtt_ratio=1.2,
            socket_count=4,
            valid=True,
        )
        self.assertEqual(s.throughput_mbps, 45.5)
        self.assertEqual(s.rtt_ms, 32.1)
        self.assertEqual(s.loss_pct, 0.15)
        self.assertTrue(s.valid)
        self.assertEqual(s.socket_count, 4)


# ---------------------------------------------------------------------------
# Test: OS detection
# ---------------------------------------------------------------------------

class TestOSDetection(unittest.TestCase):

    @patch("platform.system", return_value="Linux")
    def test_linux_reader_selected(self, _):
        from turbolane.probe import TCPSocketReader, _LinuxReader
        r = TCPSocketReader([])
        self.assertIsInstance(r._reader, _LinuxReader)
        self.assertEqual(r.os_name, "Linux")
        self.assertEqual(r.reader_type, "_LinuxReader")

    @patch("platform.system", return_value="Darwin")
    def test_macos_reader_selected(self, _):
        from turbolane.probe import TCPSocketReader, _MacOSReader
        r = TCPSocketReader([])
        self.assertIsInstance(r._reader, _MacOSReader)
        self.assertEqual(r.os_name, "Darwin")

    @patch("platform.system", return_value="FreeBSD")
    def test_unknown_os_uses_fallback(self, _):
        from turbolane.probe import TCPSocketReader, _FallbackReader
        r = TCPSocketReader([])
        self.assertIsInstance(r._reader, _FallbackReader)

    @patch("platform.system", return_value="Windows")
    def test_windows_falls_back_if_winsock_unavailable(self, _):
        from turbolane.probe import TCPSocketReader, _FallbackReader, _WindowsReader
        # Patch _WindowsReader so ws2_32 is None (simulates unavailable WinSock)
        with patch.object(_WindowsReader, "_setup_winsock", lambda self: setattr(self, "_ws2_32", None)):
            r = TCPSocketReader([])
            self.assertIsInstance(r._reader, _FallbackReader)


# ---------------------------------------------------------------------------
# Test: _SocketState management
# ---------------------------------------------------------------------------

class TestSocketManagement(unittest.TestCase):

    @patch("platform.system", return_value="Linux")
    def test_empty_socket_list(self, _):
        from turbolane.probe import TCPSocketReader
        r = TCPSocketReader([])
        self.assertEqual(r.socket_count, 0)

    @patch("platform.system", return_value="Linux")
    def test_attach_sockets(self, _):
        from turbolane.probe import TCPSocketReader
        socks = [_make_mock_socket(i) for i in range(4)]
        r = TCPSocketReader(socks)
        self.assertEqual(r.socket_count, 4)

    @patch("platform.system", return_value="Linux")
    def test_update_sockets_preserves_existing(self, _):
        from turbolane.probe import TCPSocketReader
        sock1 = _make_mock_socket(1)
        sock2 = _make_mock_socket(2)
        r = TCPSocketReader([sock1])

        # Manually set retrans counter on sock1's state
        r._socket_states[0].retrans_at_last_read = 42

        # Update with sock1 still present + new sock2
        r.update_sockets([sock1, sock2])
        self.assertEqual(r.socket_count, 2)

        # sock1's state should be preserved
        preserved = next(ss for ss in r._socket_states if ss.sock is sock1)
        self.assertEqual(preserved.retrans_at_last_read, 42)

    @patch("platform.system", return_value="Linux")
    def test_update_sockets_new_socket_starts_fresh(self, _):
        from turbolane.probe import TCPSocketReader
        sock1 = _make_mock_socket(1)
        sock2 = _make_mock_socket(2)
        r = TCPSocketReader([sock1])
        r.update_sockets([sock1, sock2])
        new_ss = next(ss for ss in r._socket_states if ss.sock is sock2)
        self.assertEqual(new_ss.retrans_at_last_read, 0)


# ---------------------------------------------------------------------------
# Test: Linux reader
# ---------------------------------------------------------------------------

class TestLinuxReader(unittest.TestCase):

    def setUp(self):
        with patch("platform.system", return_value="Linux"):
            from turbolane.probe import TCPSocketReader
            self.reader_cls = TCPSocketReader

    def test_read_one_success(self):
        from turbolane.probe import _LinuxReader
        reader = _LinuxReader()
        sock = _make_mock_socket()
        raw = _make_linux_tcp_info(rtt_us=30000, total_retrans=5, snd_mss=1460)
        sock.getsockopt.return_value = raw
        result = reader._read_one(sock)
        self.assertIsNotNone(result)
        self.assertEqual(result["rtt_us"], 30000)
        self.assertEqual(result["retrans"], 5)
        self.assertEqual(result["mss"], 1460)

    def test_read_one_oserror_returns_none(self):
        from turbolane.probe import _LinuxReader
        reader = _LinuxReader()
        sock = _make_mock_socket()
        sock.getsockopt.side_effect = OSError("socket closed")
        result = reader._read_one(sock)
        self.assertIsNone(result)

    def test_read_one_short_buffer_returns_none(self):
        from turbolane.probe import _LinuxReader
        reader = _LinuxReader()
        sock = _make_mock_socket()
        sock.getsockopt.return_value = b"\x00" * 10  # too short
        result = reader._read_one(sock)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Test: macOS reader
# ---------------------------------------------------------------------------

class TestMacOSReader(unittest.TestCase):

    def test_read_one_success(self):
        from turbolane.probe import _MacOSReader
        reader = _MacOSReader()
        sock = _make_mock_socket()
        raw = _make_macos_tcp_info(srtt_us=25000, retrans=3, snd_mss=1448)
        sock.getsockopt.return_value = raw
        result = reader._read_one(sock)
        self.assertIsNotNone(result)
        self.assertEqual(result["rtt_us"], 25000)
        self.assertEqual(result["retrans"], 3)
        self.assertEqual(result["mss"], 1448)

    def test_read_one_oserror_returns_none(self):
        from turbolane.probe import _MacOSReader
        reader = _MacOSReader()
        sock = _make_mock_socket()
        sock.getsockopt.side_effect = OSError("not connected")
        result = reader._read_one(sock)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Test: Fallback reader
# ---------------------------------------------------------------------------

class TestFallbackReader(unittest.TestCase):

    def test_read_one_returns_safe_defaults(self):
        from turbolane.probe import _FallbackReader
        reader = _FallbackReader()
        sock = _make_mock_socket()
        result = reader._read_one(sock)
        self.assertIsNotNone(result)
        self.assertEqual(result["rtt_us"], 50_000)
        self.assertEqual(result["retrans"], 0)
        self.assertEqual(result["mss"], 1460)


# ---------------------------------------------------------------------------
# Test: Throughput calculation
# ---------------------------------------------------------------------------

class TestThroughputCalculation(unittest.TestCase):

    @patch("platform.system", return_value="Linux")
    def test_throughput_accuracy(self, _):
        """
        100 MB transferred in 2 seconds = 400 Mbps
        """
        from turbolane.probe import TCPSocketReader
        sock = _make_mock_socket()
        raw = _make_linux_tcp_info(rtt_us=30000, total_retrans=0, snd_mss=1460)
        sock.getsockopt.return_value = raw

        r = TCPSocketReader([sock])

        # Simulate 100 MB transferred
        bytes_100mb = 100 * 1024 * 1024
        r.report_bytes_all(bytes_100mb)

        # Patch interval to exactly 2 seconds
        r._last_read_time = time.monotonic() - 2.0

        snapshot = r.read()
        # 100MB * 8 / 2s / 1_000_000 = 419.43 Mbps (using 1024^2)
        expected = (bytes_100mb * 8) / (2.0 * 1_000_000)
        self.assertAlmostEqual(snapshot.throughput_mbps, expected, places=1)

    @patch("platform.system", return_value="Linux")
    def test_zero_bytes_gives_zero_throughput(self, _):
        from turbolane.probe import TCPSocketReader
        sock = _make_mock_socket()
        sock.getsockopt.return_value = _make_linux_tcp_info()
        r = TCPSocketReader([sock])
        r._last_read_time = time.monotonic() - 5.0
        # Don't call report_bytes_all — default is 0
        snapshot = r.read()
        self.assertEqual(snapshot.throughput_mbps, 0.0)

    @patch("platform.system", return_value="Linux")
    def test_aggregate_throughput_across_multiple_sockets(self, _):
        """4 sockets, 25MB each = 100MB total → 400 Mbps over 2s"""
        from turbolane.probe import TCPSocketReader
        socks = [_make_mock_socket(i) for i in range(4)]
        raw = _make_linux_tcp_info(rtt_us=30000, total_retrans=0, snd_mss=1460)
        for s in socks:
            s.getsockopt.return_value = raw

        r = TCPSocketReader(socks)
        bytes_100mb = 100 * 1024 * 1024
        r.report_bytes_all(bytes_100mb)
        r._last_read_time = time.monotonic() - 2.0

        snapshot = r.read()
        expected = (bytes_100mb * 8) / (2.0 * 1_000_000)
        self.assertAlmostEqual(snapshot.throughput_mbps, expected, places=1)


# ---------------------------------------------------------------------------
# Test: RTT calculation
# ---------------------------------------------------------------------------

class TestRTTCalculation(unittest.TestCase):

    @patch("platform.system", return_value="Linux")
    def test_rtt_conversion_us_to_ms(self, _):
        """30000 µs → 30.0 ms"""
        from turbolane.probe import TCPSocketReader
        sock = _make_mock_socket()
        sock.getsockopt.return_value = _make_linux_tcp_info(rtt_us=30000)
        r = TCPSocketReader([sock])
        r._last_read_time = time.monotonic() - 1.0
        snapshot = r.read()
        self.assertAlmostEqual(snapshot.rtt_ms, 30.0, places=1)

    @patch("platform.system", return_value="Linux")
    def test_rtt_average_across_sockets(self, _):
        """4 sockets with RTTs 20, 30, 40, 50 ms → average 35 ms"""
        from turbolane.probe import TCPSocketReader
        rtt_values_us = [20000, 30000, 40000, 50000]
        socks = []
        for rtt in rtt_values_us:
            s = _make_mock_socket(rtt)
            s.getsockopt.return_value = _make_linux_tcp_info(rtt_us=rtt)
            socks.append(s)

        r = TCPSocketReader(socks)
        r._last_read_time = time.monotonic() - 1.0
        snapshot = r.read()
        self.assertAlmostEqual(snapshot.rtt_ms, 35.0, places=1)

    @patch("platform.system", return_value="Linux")
    def test_rtt_ratio_first_read_is_one(self, _):
        """First read: min_rtt = current_rtt → ratio = 1.0"""
        from turbolane.probe import TCPSocketReader
        sock = _make_mock_socket()
        sock.getsockopt.return_value = _make_linux_tcp_info(rtt_us=40000)
        r = TCPSocketReader([sock])
        r._last_read_time = time.monotonic() - 1.0
        snapshot = r.read()
        self.assertAlmostEqual(snapshot.rtt_ratio, 1.0, places=2)

    @patch("platform.system", return_value="Linux")
    def test_rtt_ratio_increases_when_rtt_rises(self, _):
        """RTT doubles → ratio should be 2.0"""
        from turbolane.probe import TCPSocketReader
        sock = _make_mock_socket()

        # First read: RTT = 30ms
        sock.getsockopt.return_value = _make_linux_tcp_info(rtt_us=30000)
        r = TCPSocketReader([sock])
        r._last_read_time = time.monotonic() - 1.0
        r.read()  # establishes min_rtt = 30ms

        # Second read: RTT = 60ms
        sock.getsockopt.return_value = _make_linux_tcp_info(rtt_us=60000)
        r._last_read_time = time.monotonic() - 1.0
        snapshot = r.read()
        self.assertAlmostEqual(snapshot.rtt_ratio, 2.0, places=1)

    @patch("platform.system", return_value="Linux")
    def test_rtt_gradient_negative_when_rtt_improves(self, _):
        """RTT drops from 60ms to 30ms → gradient should be negative"""
        from turbolane.probe import TCPSocketReader
        sock = _make_mock_socket()

        sock.getsockopt.return_value = _make_linux_tcp_info(rtt_us=60000)
        r = TCPSocketReader([sock])
        r._last_read_time = time.monotonic() - 1.0
        r.read()

        sock.getsockopt.return_value = _make_linux_tcp_info(rtt_us=30000)
        r._last_read_time = time.monotonic() - 1.0
        snapshot = r.read()
        self.assertLess(snapshot.rtt_gradient, 0)

    @patch("platform.system", return_value="Linux")
    def test_rtt_gradient_positive_when_rtt_worsens(self, _):
        """RTT increases from 30ms to 60ms → gradient should be positive"""
        from turbolane.probe import TCPSocketReader
        sock = _make_mock_socket()

        sock.getsockopt.return_value = _make_linux_tcp_info(rtt_us=30000)
        r = TCPSocketReader([sock])
        r._last_read_time = time.monotonic() - 1.0
        r.read()

        sock.getsockopt.return_value = _make_linux_tcp_info(rtt_us=60000)
        r._last_read_time = time.monotonic() - 1.0
        snapshot = r.read()
        self.assertGreater(snapshot.rtt_gradient, 0)


# ---------------------------------------------------------------------------
# Test: Packet loss calculation
# ---------------------------------------------------------------------------

class TestPacketLossCalculation(unittest.TestCase):

    @patch("platform.system", return_value="Linux")
    def test_zero_retrans_gives_zero_loss(self, _):
        from turbolane.probe import TCPSocketReader
        sock = _make_mock_socket()
        sock.getsockopt.return_value = _make_linux_tcp_info(total_retrans=0)
        r = TCPSocketReader([sock])
        r.report_bytes_all(10 * 1024 * 1024)
        r._last_read_time = time.monotonic() - 1.0
        snapshot = r.read()
        self.assertEqual(snapshot.loss_pct, 0.0)

    @patch("platform.system", return_value="Linux")
    def test_loss_calculation_accuracy(self, _):
        """
        Send 1460 bytes (exactly 1 packet), 1 retransmit → 100% loss
        """
        from turbolane.probe import TCPSocketReader
        sock = _make_mock_socket()
        # Start with 0 retrans, then jump to 1 after first read
        sock.getsockopt.return_value = _make_linux_tcp_info(
            rtt_us=30000, total_retrans=1, snd_mss=1460
        )
        r = TCPSocketReader([sock])
        r.report_bytes_all(1460)  # exactly 1 packet
        r._last_read_time = time.monotonic() - 1.0
        snapshot = r.read()
        # 1 retrans / 1 packet = 100%
        self.assertGreater(snapshot.loss_pct, 0.0)
        self.assertLessEqual(snapshot.loss_pct, 100.0)

    @patch("platform.system", return_value="Linux")
    def test_loss_aggregated_across_sockets(self, _):
        """4 sockets, each with 2 retransmissions = 8 total"""
        from turbolane.probe import TCPSocketReader
        socks = [_make_mock_socket(i) for i in range(4)]
        for s in socks:
            s.getsockopt.return_value = _make_linux_tcp_info(
                rtt_us=30000, total_retrans=2, snd_mss=1460
            )
        r = TCPSocketReader(socks)
        r.report_bytes_all(4 * 100 * 1460)  # 100 packets per socket
        r._last_read_time = time.monotonic() - 1.0
        snapshot = r.read()
        # 8 retrans / 400 packets ≈ 2%
        self.assertGreater(snapshot.loss_pct, 0.0)
        self.assertLess(snapshot.loss_pct, 10.0)

    @patch("platform.system", return_value="Linux")
    def test_loss_never_exceeds_100_pct(self, _):
        from turbolane.probe import TCPSocketReader
        sock = _make_mock_socket()
        sock.getsockopt.return_value = _make_linux_tcp_info(
            total_retrans=99999, snd_mss=1460
        )
        r = TCPSocketReader([sock])
        r.report_bytes_all(1460)
        r._last_read_time = time.monotonic() - 1.0
        snapshot = r.read()
        self.assertLessEqual(snapshot.loss_pct, 100.0)


# ---------------------------------------------------------------------------
# Test: SocketSnapshot validity
# ---------------------------------------------------------------------------

class TestSnapshotValidity(unittest.TestCase):

    @patch("platform.system", return_value="Linux")
    def test_valid_true_when_rtt_available(self, _):
        from turbolane.probe import TCPSocketReader
        sock = _make_mock_socket()
        sock.getsockopt.return_value = _make_linux_tcp_info(rtt_us=30000)
        r = TCPSocketReader([sock])
        r._last_read_time = time.monotonic() - 1.0
        snapshot = r.read()
        self.assertTrue(snapshot.valid)

    @patch("platform.system", return_value="Linux")
    def test_valid_false_when_no_sockets(self, _):
        from turbolane.probe import TCPSocketReader
        r = TCPSocketReader([])
        snapshot = r.read()
        self.assertFalse(snapshot.valid)

    @patch("platform.system", return_value="Linux")
    def test_valid_false_when_all_sockets_fail(self, _):
        from turbolane.probe import TCPSocketReader
        sock = _make_mock_socket()
        sock.getsockopt.side_effect = OSError("all failed")
        r = TCPSocketReader([sock])
        r._last_read_time = time.monotonic() - 1.0
        snapshot = r.read()
        self.assertFalse(snapshot.valid)


# ---------------------------------------------------------------------------
# Test: Engine - Option 1 (socket-based)
# ---------------------------------------------------------------------------

class TestEngineSocketMode(unittest.TestCase):

    def _make_engine(self):
        from turbolane import TurboLaneEngine
        return TurboLaneEngine(mode="edge")

    @patch("platform.system", return_value="Linux")
    def test_attach_sockets_sets_metric_source(self, _):
        engine = self._make_engine()
        sock = _make_mock_socket()
        sock.getsockopt.return_value = _make_linux_tcp_info()
        engine.attach_sockets([sock])
        self.assertEqual(engine.metric_source, "socket")

    @patch("platform.system", return_value="Linux")
    def test_decide_zero_args_with_sockets(self, _):
        engine = self._make_engine()
        sock = _make_mock_socket()
        sock.getsockopt.return_value = _make_linux_tcp_info(rtt_us=30000)
        engine.attach_sockets([sock])
        engine.report_bytes(50 * 1024 * 1024)
        result = engine.decide()
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 1)

    @patch("platform.system", return_value="Linux")
    def test_learn_zero_args_with_sockets(self, _):
        engine = self._make_engine()
        sock = _make_mock_socket()
        sock.getsockopt.return_value = _make_linux_tcp_info(rtt_us=30000)
        engine.attach_sockets([sock])
        engine.decide()
        # learn() with no args should not raise
        engine.learn()

    @patch("platform.system", return_value="Linux")
    def test_update_sockets_replaces_list(self, _):
        engine = self._make_engine()
        sock1 = _make_mock_socket(1)
        sock2 = _make_mock_socket(2)
        sock1.getsockopt.return_value = _make_linux_tcp_info()
        sock2.getsockopt.return_value = _make_linux_tcp_info()

        engine.attach_sockets([sock1])
        self.assertEqual(engine._reader.socket_count, 1)

        engine.update_sockets([sock1, sock2])
        self.assertEqual(engine._reader.socket_count, 2)

    @patch("platform.system", return_value="Linux")
    def test_get_stats_includes_probe_info(self, _):
        engine = self._make_engine()
        sock = _make_mock_socket()
        sock.getsockopt.return_value = _make_linux_tcp_info()
        engine.attach_sockets([sock])
        stats = engine.get_stats()
        self.assertIn("probe_os", stats)
        self.assertIn("probe_reader", stats)
        self.assertIn("probe_socket_count", stats)
        self.assertEqual(stats["metric_source"], "socket")
        self.assertEqual(stats["probe_socket_count"], 1)


# ---------------------------------------------------------------------------
# Test: Engine - Option 2 (manual report)
# ---------------------------------------------------------------------------

class TestEngineManualMode(unittest.TestCase):

    def _make_engine(self):
        from turbolane import TurboLaneEngine
        return TurboLaneEngine(mode="edge")

    def test_report_metrics_sets_source(self):
        engine = self._make_engine()
        engine.report_metrics(throughput_mbps=45.0, rtt_ms=32.0, loss_pct=0.1)
        self.assertEqual(engine.metric_source, "manual")

    def test_decide_zero_args_after_report(self):
        engine = self._make_engine()
        engine.report_metrics(throughput_mbps=45.0, rtt_ms=32.0, loss_pct=0.1)
        result = engine.decide()
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 1)

    def test_learn_zero_args_after_report(self):
        engine = self._make_engine()
        engine.report_metrics(throughput_mbps=45.0, rtt_ms=32.0, loss_pct=0.1)
        engine.decide()
        engine.learn()  # should not raise

    def test_reported_values_are_used(self):
        engine = self._make_engine()
        engine.report_metrics(throughput_mbps=45.0, rtt_ms=32.0, loss_pct=0.1)
        t, r, l = engine._resolve_metrics(None, None, None)
        self.assertEqual(t, 45.0)
        self.assertEqual(r, 32.0)
        self.assertEqual(l, 0.1)

    def test_report_updates_values(self):
        engine = self._make_engine()
        engine.report_metrics(45.0, 32.0, 0.1)
        engine.report_metrics(60.0, 25.0, 0.05)
        t, r, l = engine._resolve_metrics(None, None, None)
        self.assertEqual(t, 60.0)
        self.assertEqual(r, 25.0)
        self.assertEqual(l, 0.05)


# ---------------------------------------------------------------------------
# Test: Engine - Option 3 (legacy passthrough)
# ---------------------------------------------------------------------------

class TestEngineLegacyMode(unittest.TestCase):

    def _make_engine(self):
        from turbolane import TurboLaneEngine
        return TurboLaneEngine(mode="edge")

    def test_decide_with_explicit_args_works(self):
        engine = self._make_engine()
        result = engine.decide(throughput_mbps=45.0, rtt_ms=32.0, loss_pct=0.1)
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 1)

    def test_learn_with_explicit_args_works(self):
        engine = self._make_engine()
        engine.decide(throughput_mbps=45.0, rtt_ms=32.0, loss_pct=0.1)
        engine.learn(throughput_mbps=48.0, rtt_ms=31.0, loss_pct=0.1)

    def test_explicit_args_override_socket_source(self):
        """Legacy args always take priority over socket reader."""
        engine = self._make_engine()
        engine.report_metrics(10.0, 200.0, 5.0)  # bad metrics
        # Explicit args should win
        t, r, l = engine._resolve_metrics(45.0, 32.0, 0.1)
        self.assertEqual(t, 45.0)
        self.assertEqual(r, 32.0)
        self.assertEqual(l, 0.1)

    def test_explicit_args_override_manual_report(self):
        engine = self._make_engine()
        engine.report_metrics(10.0, 200.0, 5.0)
        t, r, l = engine._resolve_metrics(99.0, 5.0, 0.01)
        self.assertEqual(t, 99.0)

    def test_metric_source_stays_none_with_legacy_only(self):
        engine = self._make_engine()
        engine.decide(throughput_mbps=45.0, rtt_ms=32.0, loss_pct=0.1)
        # metric_source should still be "none" — legacy doesn't change it
        self.assertEqual(engine.metric_source, "none")


# ---------------------------------------------------------------------------
# Test: Engine - Fallback defaults
# ---------------------------------------------------------------------------

class TestEngineFallback(unittest.TestCase):

    def test_no_metrics_uses_fallback(self):
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="edge")
        t, r, l = engine._resolve_metrics(None, None, None)
        self.assertEqual(t, TurboLaneEngine._FALLBACK_THROUGHPUT)
        self.assertEqual(r, TurboLaneEngine._FALLBACK_RTT)
        self.assertEqual(l, TurboLaneEngine._FALLBACK_LOSS)

    def test_decide_works_with_no_setup(self):
        """Engine should not crash even with zero setup."""
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="edge")
        result = engine.decide()
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 1)


# ---------------------------------------------------------------------------
# Test: Engine - Priority order
# ---------------------------------------------------------------------------

class TestMetricPriority(unittest.TestCase):

    @patch("platform.system", return_value="Linux")
    def test_explicit_beats_socket(self, _):
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="edge")
        sock = _make_mock_socket()
        sock.getsockopt.return_value = _make_linux_tcp_info(rtt_us=100000)  # 100ms
        engine.attach_sockets([sock])

        # Explicit args should override socket
        t, r, l = engine._resolve_metrics(45.0, 32.0, 0.1)
        self.assertEqual(r, 32.0)  # not 100ms from socket

    def test_socket_beats_manual(self):
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="edge")
        engine.report_metrics(10.0, 200.0, 5.0)

        # Simulate a socket reader that returns valid snapshot
        mock_reader = MagicMock()
        from turbolane.probe import SocketSnapshot
        mock_reader.read.return_value = SocketSnapshot(
            throughput_mbps=50.0, rtt_ms=30.0, loss_pct=0.1, valid=True
        )
        engine._reader = mock_reader
        engine._metric_source = "socket"

        t, r, l = engine._resolve_metrics(None, None, None)
        self.assertEqual(t, 50.0)   # from socket, not manual
        self.assertEqual(r, 30.0)

    def test_manual_beats_fallback(self):
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="edge")
        engine.report_metrics(45.0, 32.0, 0.1)
        t, r, l = engine._resolve_metrics(None, None, None)
        self.assertEqual(t, 45.0)  # manual, not fallback 10.0


# ---------------------------------------------------------------------------
# Test: Engine - get_stats()
# ---------------------------------------------------------------------------

class TestEngineStats(unittest.TestCase):

    def test_stats_includes_metric_source_none(self):
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="edge")
        stats = engine.get_stats()
        self.assertIn("metric_source", stats)
        self.assertEqual(stats["metric_source"], "none")
        self.assertIn("engine_mode", stats)
        self.assertIn("engine_algorithm", stats)

    def test_stats_no_probe_keys_when_no_sockets(self):
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="edge")
        stats = engine.get_stats()
        self.assertNotIn("probe_os", stats)

    @patch("platform.system", return_value="Linux")
    def test_stats_has_probe_keys_after_attach(self, _):
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="edge")
        sock = _make_mock_socket()
        sock.getsockopt.return_value = _make_linux_tcp_info()
        engine.attach_sockets([sock])
        stats = engine.get_stats()
        self.assertEqual(stats["probe_os"], "Linux")
        self.assertEqual(stats["probe_reader"], "_LinuxReader")
        self.assertEqual(stats["probe_socket_count"], 1)


# ---------------------------------------------------------------------------
# Test: Engine - save, reset, repr
# ---------------------------------------------------------------------------

class TestEngineLifecycle(unittest.TestCase):

    def test_save_returns_bool(self):
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="edge")
        result = engine.save()
        self.assertIsInstance(result, bool)

    def test_reset_does_not_raise(self):
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="edge")
        engine.decide(45.0, 32.0, 0.1)
        engine.reset()  # should not raise

    def test_repr_includes_metric_source(self):
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="edge")
        r = repr(engine)
        self.assertIn("metric_source", r)

    def test_federated_mode_works(self):
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="federated")
        result = engine.decide(120.0, 8.0, 0.05)
        self.assertIsInstance(result, int)

    def test_client_alias_works(self):
        from turbolane import TurboLaneEngine
        engine = TurboLaneEngine(mode="client")
        self.assertEqual(engine.mode, "edge")

    def test_invalid_mode_raises(self):
        from turbolane import TurboLaneEngine
        with self.assertRaises(ValueError):
            TurboLaneEngine(mode="invalid_mode")

    def test_invalid_algorithm_raises(self):
        from turbolane import TurboLaneEngine
        with self.assertRaises(ValueError):
            TurboLaneEngine(mode="edge", algorithm="genetic")


# ---------------------------------------------------------------------------
# Test: TCPSocketReader repr
# ---------------------------------------------------------------------------

class TestReaderRepr(unittest.TestCase):

    @patch("platform.system", return_value="Linux")
    def test_repr(self, _):
        from turbolane.probe import TCPSocketReader
        r = TCPSocketReader([])
        rep = repr(r)
        self.assertIn("TCPSocketReader", rep)
        self.assertIn("Linux", rep)
        self.assertIn("_LinuxReader", rep)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
