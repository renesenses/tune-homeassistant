"""Constants for Tune Music Server integration."""

DOMAIN = "tune"
DEFAULT_PORT = 8888
DEFAULT_HOST = "localhost"

CONF_HOST = "host"
CONF_PORT = "port"
# Optional: only needed when authentication is enabled on the Tune server
# (Settings > Security). Sent as `Authorization: ApiKey <key>`.
CONF_API_KEY = "api_key"

API_BASE = "/api/v1"

# Polling interval (seconds) — fallback when WebSocket is unavailable
POLL_INTERVAL = 10

# WebSocket reconnect delay bounds (seconds)
WS_RECONNECT_MIN = 1
WS_RECONNECT_MAX = 30


def auth_headers(api_key: str | None) -> dict[str, str]:
    """HTTP headers carrying the Tune API key, if any."""
    return {"Authorization": f"ApiKey {api_key}"} if api_key else {}
