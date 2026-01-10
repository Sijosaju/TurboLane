"""
downloader/downloader.py - Multi-Stream Downloader with RL-based Optimization
Supports PPO and Q-learning.
JSON-SAFE version (session persistence fixed).
"""

import os
import requests
import threading
import time
import subprocess
import platform
from urllib.parse import urlparse, unquote
from collections import deque

from downloader.config import *

try:
    from turbolane import TurboLaneEngine
    TURBOLANE_AVAILABLE = True
except ImportError:
    TURBOLANE_AVAILABLE = False


class MultiStreamDownloader:
    """
    Multi-stream downloader with reinforcement learning-based dynamic optimization.
    """

    def __init__(self, url, num_streams=DEFAULT_NUM_STREAMS,
                 progress_callback=None, use_rl=False, algorithm=None):

        self.url = url
        self.num_streams = min(max(num_streams, MIN_STREAMS), MAX_STREAMS)
        self.progress_callback = progress_callback
        self.use_rl = use_rl and TURBOLANE_AVAILABLE
        self.algorithm = algorithm or RL_ALGORITHM

        if self.use_rl:
            self.turbolane = TurboLaneEngine(mode='client', algorithm=self.algorithm)
            self.current_stream_count = self.turbolane.policy.agent.current_connections
            print(f"🤖 RL Mode: {self.algorithm.upper()} optimization enabled")
            print(f"   Initial streams: {self.current_stream_count}")
        else:
            self.current_stream_count = self.num_streams
            print(f"📊 Static Mode: Using {self.num_streams} streams")

        # Download state
        self.file_size = 0
        self.downloaded_bytes = 0
        self.chunks = []
        self.temp_files = []
        self.is_downloading = False
        self.threads = []
        self.lock = threading.Lock()
        self.start_time = None

        # Metrics
        self.chunk_speeds = {}
        self.failed_chunks = set()
        self.active_chunks = set()

        self.metrics_history = deque(maxlen=10)
        self.last_packet_loss = 0.1
        self.last_utility = None
        self.last_mi_time = time.time()

        self.network_metrics = {
            "throughput": 0.0,
            "rtt": 100.0,
            "packet_loss": 0.1,
            "utility": 0.0,
            "reward": 0.0,
        }

    # =====================================================
    # ✅ JSON SAFE SNAPSHOT
    # =====================================================
    def to_dict(self):
        return {
            "url": self.url,
            "file_size": self.file_size,
            "downloaded_bytes": self.downloaded_bytes,
            "progress": (self.downloaded_bytes / self.file_size * 100)
                        if self.file_size > 0 else 0.0,
            "current_streams": self.current_stream_count,
            "use_rl": self.use_rl,
            "algorithm": self.algorithm if self.use_rl else "static",
            "is_downloading": self.is_downloading,
            "elapsed_time": time.time() - self.start_time if self.start_time else 0.0,
            "throughput_mbps": self.calculate_throughput(),
            "network_metrics": self.network_metrics.copy(),
        }

    # =====================================================
    # ✅ 🔥 FIX: DETAILED METRICS (USED BY app.py)
    # =====================================================
    def get_detailed_metrics(self):
        """
        Detailed metrics for Flask API.
        MUST be JSON serializable.
        """
        return {
            "throughput_mbps": self.calculate_throughput(),
            "current_streams": self.current_stream_count,
            "file_size": self.file_size,
            "downloaded_bytes": self.downloaded_bytes,
            "elapsed_time": time.time() - self.start_time if self.start_time else 0.0,
            "network_metrics": self.network_metrics.copy(),
            "use_rl": self.use_rl,
            "algorithm": self.algorithm if self.use_rl else "static"
        }

    # =====================================================
    # Network Metrics
    # =====================================================
    def calculate_throughput(self):
        if not self.start_time or self.downloaded_bytes == 0:
            return 0.0
        elapsed = time.time() - self.start_time
        if elapsed <= 0:
            return 0.0
        return (self.downloaded_bytes * 8) / elapsed / (1024 * 1024)

    def measure_rtt(self):
        try:
            host = urlparse(self.url).hostname
            param = "-n" if platform.system().lower() == "windows" else "-c"
            result = subprocess.run(
                ["ping", param, "1", host],
                capture_output=True, text=True, timeout=3
            )
            output = result.stdout.lower()
            if "time=" in output:
                return float(output.split("time=")[1].split()[0].replace("ms", ""))
        except Exception:
            pass
        return 100.0

    def estimate_packet_loss(self):
        if not self.chunk_speeds:
            return 0.1
        speeds = list(self.chunk_speeds.values())
        avg = sum(speeds) / len(speeds)
        variance = sum((s - avg) ** 2 for s in speeds) / len(speeds)
        loss = min(5.0, (variance ** 0.5 / max(avg, 0.1)) * 2.0)
        self.last_packet_loss = 0.7 * self.last_packet_loss + 0.3 * loss
        return max(0.1, min(5.0, self.last_packet_loss))

    def update_network_metrics(self):
        t = self.calculate_throughput()
        rtt = self.measure_rtt()
        loss = self.estimate_packet_loss()

        utility = (
            t / (UTILITY_K ** max(1, self.current_stream_count))
            - (t * (loss / 100) * UTILITY_B)
        )

        reward = 0.0 if self.last_utility is None else (
            1.0 if utility - self.last_utility > UTILITY_EPSILON else
            -1.0 if utility - self.last_utility < -UTILITY_EPSILON else 0.0
        )

        self.last_utility = utility

        self.network_metrics.update({
            "throughput": t,
            "rtt": rtt,
            "packet_loss": loss,
            "utility": utility,
            "reward": reward
        })

        print(
            f"📈 Network Metrics: T={t:.2f}Mbps, RTT={rtt:.1f}ms, "
            f"Loss={loss:.2f}%, Utility={utility:.3f}, Reward={reward:.2f}"
        )

        return t, rtt, loss

    # =====================================================
    # RL Monitoring
    # =====================================================
    def run_monitoring_interval(self):
        if not self.use_rl:
            return
        if time.time() - self.last_mi_time < RL_MONITORING_INTERVAL:
            return

        throughput, rtt, loss = self.update_network_metrics()

        self.turbolane.learn(throughput, rtt, loss)
        new_streams = self.turbolane.decide(throughput, rtt, loss)

        if new_streams != self.current_stream_count:
            print(f"🔄 Streams: {self.current_stream_count} → {new_streams}")
            self.current_stream_count = new_streams

        self.last_mi_time = time.time()

    # =====================================================
    # Download Execution
    # =====================================================
    def download(self, output_path=None):
        supports_ranges, self.file_size, filename = self.check_download_support()
        output_path = output_path or os.path.join(DOWNLOAD_FOLDER, filename)

        self.start_time = time.time()
        self.is_downloading = True

        self.chunks = self.calculate_chunks(self.file_size, MAX_STREAMS)
        remaining = set(range(len(self.chunks)))

        for _ in range(min(self.current_stream_count, len(remaining))):
            self.start_chunk(remaining.pop(), output_path)

        while remaining or any(t.is_alive() for t in self.threads):
            self.run_monitoring_interval()
            self.threads = [t for t in self.threads if t.is_alive()]
            slots = self.current_stream_count - len(self.threads)
            for _ in range(min(slots, len(remaining))):
                self.start_chunk(remaining.pop(), output_path)
            time.sleep(0.5)

        self.assemble_file(output_path)

        if self.use_rl:
            self.turbolane.save()
            print(f"🤖 RL Stats: {self.turbolane.get_stats()}")

        return output_path

    # =====================================================
    # Utilities
    # =====================================================
    def check_download_support(self):
        r = requests.head(self.url, allow_redirects=True)
        size = int(r.headers.get("Content-Length", 0))
        filename = unquote(os.path.basename(urlparse(self.url).path)) or "downloaded_file"
        return r.headers.get("Accept-Ranges") == "bytes", size, filename

    def calculate_chunks(self, size, max_streams):
        chunk_size = max(size // max_streams, MIN_CHUNK_SIZE)
        return [(i * chunk_size, min(size - 1, (i + 1) * chunk_size - 1))
                for i in range(max_streams)]

    def start_chunk(self, cid, output):
        start, end = self.chunks[cid]
        part = f"{output}.part{cid}"
        self.temp_files.append(part)
        t = threading.Thread(
            target=self.download_chunk,
            args=(cid, start, end, part),
            daemon=True
        )
        t.start()
        self.threads.append(t)

    def download_chunk(self, cid, start, end, path):
        headers = {"Range": f"bytes={start}-{end}"}
        try:
            with requests.get(self.url, headers=headers, stream=True) as r:
                with open(path, "wb") as f:
                    for chunk in r.iter_content(BUFFER_SIZE):
                        if not self.is_downloading:
                            return
                        f.write(chunk)
                        with self.lock:
                            self.downloaded_bytes += len(chunk)
        except Exception:
            self.failed_chunks.add(cid)

    def assemble_file(self, output):
        with open(output, "wb") as out:
            for part in self.temp_files:
                if os.path.exists(part):
                    with open(part, "rb") as p:
                        out.write(p.read())
                    os.remove(part)
        print("✅ File assembled successfully")
