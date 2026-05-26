"""Tests for transport factory and pluggable transport support."""

from unittest.mock import MagicMock, patch

import pytest
from litserve.transport.factory import TransportConfig
from litserve.transport.process_transport import MPQueueTransport
from litserve.transport.zmq_transport import ZMQTransport

from light_server.core.transport_factory import TransportFactory, _ensure_zmq


class TestTransportFactory:
    """TransportFactory.create() produces correct transport instances."""

    def test_create_mp_transport(self):
        config = TransportConfig(transport_type="mp", num_consumers=2)
        transport = TransportFactory.create(config)
        assert isinstance(transport, MPQueueTransport)
        assert len(transport._queues) == 2

    def test_create_zmq_transport(self):
        config = TransportConfig(transport_type="zmq", num_consumers=2)
        transport = TransportFactory.create(config)
        assert isinstance(transport, ZMQTransport)
        assert transport._broker is not None
        # Broker runs in a daemon thread; no explicit stop needed in tests
        try:
            transport.close()
        except ValueError:
            pass  # socket not initialized yet

    def test_create_invalid_transport_type(self):
        # TransportConfig rejects "unknown" at Pydantic level, so test factory directly
        class FakeConfig:
            transport_type = "unknown"
        with pytest.raises(ValueError, match="Invalid transport type"):
            TransportFactory.create(FakeConfig())

    def test_zmq_transport_pickleable(self):
        """ZMQTransport must survive pickling for spawn context."""
        import pickle

        config = TransportConfig(transport_type="zmq", num_consumers=1)
        transport = TransportFactory.create(config)
        try:
            restored = pickle.loads(pickle.dumps(transport))
            assert isinstance(restored, ZMQTransport)
            assert restored.backend_address == transport.backend_address
            assert restored.frontend_address == transport.frontend_address
        finally:
            # Broker runs in a daemon thread; no explicit stop needed in tests
            try:
                transport.close()
            except ValueError:
                pass  # socket not initialized yet


class TestEnsureZmq:
    """_ensure_zmq() detects missing pyzmq and raises helpful error."""

    def test_ensure_zmq_installed(self):
        # Should not raise when pyzmq is available
        _ensure_zmq()

    def test_ensure_zmq_missing_raises(self):
        with patch.dict("sys.modules", {"zmq": None}):
            with pytest.raises(ImportError, match="ZMQ transport requires pyzmq"):
                _ensure_zmq()


class TestServerTransportIntegration:
    """LightServer respects config.server.transport field."""

    def test_default_transport_is_mp(self, sample_config, isolated_model_repo):
        from light_server.config import Config, load_config
        import tempfile
        import yaml

        sample_config["server"]["transport"] = "mp"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(sample_config, f)
            f.flush()
            config = load_config(f.name)

        assert config.server.transport == "mp"

    def test_zmq_transport_config(self, sample_config, isolated_model_repo):
        from light_server.config import Config, load_config
        import tempfile
        import yaml

        sample_config["server"]["transport"] = "zmq"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(sample_config, f)
            f.flush()
            config = load_config(f.name)

        assert config.server.transport == "zmq"
