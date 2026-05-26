"""Pluggable transport factory for MPQueue and ZeroMQ backends."""

from __future__ import annotations

from litserve.transport.factory import TransportConfig
from litserve.transport.process_transport import MPQueueTransport


def _ensure_zmq() -> None:
    """Raise ImportError with helpful message if pyzmq is not installed."""
    try:
        import zmq  # noqa: F401
    except ImportError:
        raise ImportError(
            "ZMQ transport requires pyzmq. Install with: "
            "uv sync --extra zmq   or   pip install light-server[zmq]"
        )


class TransportFactory:
    """Create MPQueueTransport or ZMQTransport based on configuration."""

    @staticmethod
    def create(config: TransportConfig) -> MPQueueTransport:
        if config.transport_type == "mp":
            return _create_mp_transport(config)
        if config.transport_type == "zmq":
            return _create_zmq_transport(config)
        raise ValueError(f"Invalid transport type: {config.transport_type}")


def _create_mp_transport(config: TransportConfig) -> MPQueueTransport:
    from multiprocessing import Manager

    manager = config.manager or Manager()
    queues = [manager.Queue() for _ in range(config.num_consumers)]
    return MPQueueTransport(manager, queues)


def _create_zmq_transport(config: TransportConfig):
    _ensure_zmq()
    from litserve.transport.zmq_queue import Broker
    from litserve.transport.zmq_transport import ZMQTransport

    broker = Broker()
    broker.start()
    transport = ZMQTransport(broker.backend_address, broker.frontend_address)
    transport._broker = broker  # type: ignore[attr-defined]
    return transport
