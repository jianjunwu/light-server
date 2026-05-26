import os
import socket

_port_counter = 0


def _get_free_port() -> int:
    """Return an available TCP port, partitioned by xdist worker to avoid collisions."""
    global _port_counter
    worker_id = os.environ.get("_PYTEST_XDIST_WORKER", "master")
    worker_num = 0 if worker_id == "master" else int(worker_id.replace("gw", ""))

    base = 50000 + worker_num * 100
    for _ in range(100):
        port = base + _port_counter
        _port_counter = (_port_counter + 1) % 100
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue

    # Fallback: let the kernel assign
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
