<div align="center">

<br/>

```
████████╗██╗   ██╗██████╗ ██████╗  ██████╗ ██╗      █████╗ ███╗   ██╗███████╗
   ██╔══╝██║   ██║██╔══██╗██╔══██╗██╔═══██╗██║     ██╔══██╗████╗  ██║██╔════╝
   ██║   ██║   ██║██████╔╝██████╔╝██║   ██║██║     ███████║██╔██╗ ██║█████╗  
   ██║   ██║   ██║██╔══██╗██╔══██╗██║   ██║██║     ██╔══██║██║╚██╗██║██╔══╝  
   ██║   ╚██████╔╝██║  ██║██████╔╝╚██████╔╝███████╗██║  ██║██║ ╚████║███████╗
   ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝
```

**RL-based engine that finds the optimal number of parallel TCP streams for any network transfer.**

<br/>

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-22c55e?style=flat-square)
![PyPI](https://img.shields.io/badge/PyPI-turbolane--engine-f97316?style=flat-square&logo=pypi&logoColor=white)
![License](https://img.shields.io/badge/License-Proprietary-ef4444?style=flat-square)

[**Quick Start**](#quick-start) · [**How It Works**](#how-it-works) · [**Benchmarks**](#benchmarks) · [**API**](#api-reference)

<br/>

</div>

---

A single TCP connection rarely saturates available bandwidth. Too many parallel streams causes congestion. Too few wastes capacity. The right number changes constantly as RTT shifts and packet loss fluctuates.

**TurboLane solves this dynamically** — a Q-Learning agent watches your active sockets, reads real network signals from the OS TCP stack, and continuously adjusts stream count to squeeze the most out of whatever network you're on. No protocol modifications. No kernel patches. Drop it into any transfer loop in three calls.

---

## Installation

```bash
pip install turbolane-engine
```

---

## Quick Start

```python
from turbolane import TurboLaneEngine

engine = TurboLaneEngine(mode="edge")
```

**Step 1 — Attach your sockets**

```python
engine.attach_sockets([sock1, sock2, sock3, sock4])
# RTT and packet loss are now read from the OS TCP stack automatically
```

**Step 2 — Run the transfer loop**

```python
while transferring:
    bytes_sent = send_batch()

    engine.report_bytes(bytes_sent)   # bytes transferred since last call
    streams = engine.decide()         # recommended stream count
    engine.learn()                    # agent updates from outcome

    adjust_parallel_streams(streams)

engine.save()                         # persist learned Q-table to disk
```

**Step 3 — Update sockets when stream count changes**

```python
engine.update_sockets(new_socket_list)
```

---

## How It Works

TurboLane reads RTT and packet loss directly from your OS TCP stack via attached sockets — no extra instrumentation needed. At each decision step the agent sees:

| Signal | Source |
|---|---|
| Throughput | `report_bytes()` ÷ elapsed time |
| RTT | `TCP_INFO.tcpi_rtt` (Linux/macOS) · `SIO_TCP_INFO.RttUs` (Windows) |
| Packet Loss | `TCP_INFO.tcpi_total_retrans` (Linux/macOS) · `SIO_TCP_INFO.RetransmittedPackets` (Windows) |

It picks an action from **{+2, +1, 0, −1, −2}** streams, observes the throughput outcome, and updates its Q-table. The learned policy persists across sessions — every transfer makes the engine smarter for the next one.

### Architecture

```
┌──────────────────────────────────────────────────────┐
│                  Your Application                     │
│   Download Manager            DCI File Transfer       │
│   HTTP chunks · reassembly    Chunking · transmission │
└──────────────┬───────────────────────────┬───────────┘
               │  Policy selected here     │
┌──────────────▼───────────────────────────▼───────────┐
│            TurboLane Optimization Engine              │
│                                                      │
│   EdgePolicy                    FederatedPolicy      │
│   Public internet               Data-centre links    │
│   Variable BW / RTT             Stable, high-BW      │
│                                                      │
│   ┌──────────────────────────────────────────────┐  │
│   │            Shared RL Agent                   │  │
│   │   state-action mapping · Q-learning          │  │
│   │   actions: +2  +1  0  -1  -2  streams        │  │
│   └──────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

---

## Modes

| Mode | Use when |
|---|---|
| `"edge"` | Public internet — uploads, downloads, cloud transfers |
| `"federated"` | Data-centre interconnects — low latency, high bandwidth |
| `"client"` | Alias for `"edge"` |

---

## Full Example

```python
import socket
import threading
from turbolane import TurboLaneEngine

engine = TurboLaneEngine(mode="edge")

def open_sockets(host, port, n):
    sockets = []
    for _ in range(n):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        sockets.append(s)
    return sockets

def transfer(host, port, data):
    streams = engine.current_connections
    sockets = open_sockets(host, port, streams)
    engine.attach_sockets(sockets)

    chunk_size = len(data) // streams
    offset = 0

    while offset < len(data):
        streams = engine.decide()

        chunks = []
        for i in range(streams):
            chunk = data[offset : offset + chunk_size]
            if not chunk:
                break
            chunks.append((sockets[i % len(sockets)], chunk))
            offset += chunk_size

        total_bytes, lock = 0, threading.Lock()

        def send(sock, chunk):
            nonlocal total_bytes
            sock.sendall(chunk)
            with lock:
                total_bytes += len(chunk)

        threads = [threading.Thread(target=send, args=(s, c)) for s, c in chunks]
        for t in threads: t.start()
        for t in threads: t.join()

        engine.report_bytes(total_bytes)
        engine.learn()

    engine.save()
    for s in sockets:
        s.close()
```

---

## Benchmarks

Tested over a 60–65 Mbps public internet connection, downloading 2–10 GB files. Theoretical ceiling on this network: **~7.8 MB/s**.

### Throughput vs. everything else

| File Size | Chrome | Edge | Fixed TCP Streams | **TurboLane** |
|:-:|:-:|:-:|:-:|:-:|
| 2 GB | 2.8 MB/s | 3.1 MB/s | 4.1 MB/s | **6.4 MB/s** |
| 3 GB | 2.6 MB/s | 2.9 MB/s | 3.9 MB/s | **6.7 MB/s** |
| 5 GB | 2.4 MB/s | 2.7 MB/s | 3.7 MB/s | **7.0 MB/s** |
| 10 GB | 2.2 MB/s | 2.5 MB/s | 3.4 MB/s | **7.3 MB/s** |

> Up to **2.2× the throughput of the best browser**, approaching the theoretical ceiling on every file size. Performance improves with file size — longer transfers give the agent more decisions to converge on the optimal stream count.

### Agent convergence (real session data)

| Metric | Value |
|---|---|
| Total Decisions | 1,651 |
| Positive Rewards | 1,647 **(99.8%)** |
| Negative Rewards | 3 |
| Average Reward | 4.04 |
| Throughput-Improving Decisions | 790 (47.9%) |
| Final Exploration Rate | ε = 0.15 |
| Learned Q-Table States | 13 |

An exploration rate of 0.15 means the agent had converged — it was running its learned policy, not experimenting.

### What the agent actually learned

Inspecting the Q-table from real transfers reveals a clean, interpretable policy:

- **Low throughput** → strongly prefers `+2` / `+1` streams *(push harder)*
- **Mid throughput** → hold or modest increase *(stable ground)*
- **Near bandwidth ceiling** → avoids adding more streams *(don't cause congestion)*

Exactly what you'd write by hand if you knew the network — except the agent derived it from observed rewards alone.

---

## API Reference

| Method | Returns | Description |
|---|---|---|
| `attach_sockets(sockets)` | `None` | Attach active `socket.socket` list. Engine reads RTT and packet loss from OS automatically. |
| `update_sockets(sockets)` | `None` | Replace socket list when stream count changes. Existing counters preserved for sockets still present. |
| `report_bytes(total_bytes)` | `None` | Report bytes transferred across all streams since last call. Used to compute throughput. |
| `decide()` | `int` | Returns recommended stream count based on current network conditions. |
| `learn()` | `None` | Update Q-table from the outcome of the previous decision. |
| `save()` | `bool` | Persist Q-table to disk. Returns `True` on success. |
| `get_stats()` | `dict` | Current engine state — connections, Q-table size, rewards, metric source. |
| `reset()` | `None` | Clear Q-table from memory. Does not delete the saved file on disk. |
| `current_connections` | `int` | Property. Current recommended stream count. |

---

## Model Storage

TurboLane saves its learned Q-table to the OS user data directory:

| OS | Path |
|---|---|
| Linux | `~/.local/share/TurboLane/models/<profile>` |
| macOS | `~/Library/Application Support/TurboLane/models/<profile>` |
| Windows | `%LOCALAPPDATA%\TurboLane\models\<profile>` |
| Fallback | `./.turbolane/models/<profile>` |

Custom path:

```python
engine = TurboLaneEngine(mode="edge", model_dir="/your/path/models/edge")
```

---

## When TurboLane helps (and when it doesn't)

**Great fit:**
- WAN downloads/uploads with variable latency or packet loss
- Cloud migration and large dataset transfers over public internet
- Any pipeline where network conditions change during a transfer

**Limited benefit:**
- LAN transfers with near-zero RTT and negligible packet loss — when a network is already ideal there's no headroom to optimize. TurboLane adds no overhead, it just won't beat a fixed-stream approach because there's nothing left to squeeze out.

---

## License

Proprietary — TurboLane Team