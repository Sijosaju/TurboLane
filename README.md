# TurboLane Engine

RL-based engine that finds the optimal number of parallel TCP streams for any network transfer.

```bash
pip install turbolane-engine
```

**Requirements:** Python ≥ 3.10 · Linux · macOS · Windows

---

## How It Works

A single TCP connection rarely saturates available bandwidth. Using N parallel streams
multiplies throughput — but too many causes congestion. TurboLane uses a Q-Learning agent
to find the right N dynamically, reading all network signals directly from your active
sockets via the OS TCP stack.

---

## Quick Start

```python
from turbolane import TurboLaneEngine

engine = TurboLaneEngine(mode="edge")
```

---

## Modes

| Mode | Use when |
|---|---|
| `"edge"` | Public internet — uploads, downloads, cloud transfers |
| `"federated"` | Data centre interconnects — low latency, high bandwidth |
| `"client"` | Alias for `"edge"` |

---

## Integration

### Step 1 — Attach your sockets

After opening your parallel transfer sockets, pass them to the engine once.
TurboLane reads RTT and packet loss from the OS TCP stack automatically.

```python
engine.attach_sockets([sock1, sock2, sock3, sock4])
```

### Step 2 — Run the transfer loop

```python
while transferring:
    bytes_sent = send_batch()             # your transfer logic

    engine.report_bytes(bytes_sent)       # bytes transferred since last call
    streams = engine.decide()             # engine returns recommended stream count
    engine.learn()                        # engine updates from what it observed

    adjust_parallel_streams(streams)      # open/close sockets to match

engine.save()                             # persist learned state to disk
```

### Step 3 — Update sockets when stream count changes

```python
# After opening or closing sockets to match the new stream count:
engine.update_sockets(new_socket_list)
```

---

## What the Engine Collects Automatically

Once sockets are attached, TurboLane reads everything from the OS with no extra work from you:

| Metric | Source |
|---|---|
| Throughput | Computed from `report_bytes()` ÷ elapsed time |
| RTT | `TCP_INFO.tcpi_rtt` (Linux / macOS) · `SIO_TCP_INFO.RttUs` (Windows) |
| Packet Loss | `TCP_INFO.tcpi_total_retrans` (Linux / macOS) · `SIO_TCP_INFO.RetransmittedPackets` (Windows) |

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

## License

Proprietary — TurboLane Team