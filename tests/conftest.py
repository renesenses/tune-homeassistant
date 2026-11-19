"""Fixtures for the Tune integration tests."""
from unittest.mock import patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/tune."""
    yield


@pytest.fixture
def no_websocket():
    """Mocked HTTP only: do not open the WebSocket listener."""
    async def _idle(self):
        return None

    with patch("custom_components.tune.coordinator.TuneCoordinator._ws_loop", _idle):
        yield
