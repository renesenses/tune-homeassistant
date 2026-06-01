"""Constants for Tune Music Server integration."""

DOMAIN = "tune"
DEFAULT_PORT = 8888
DEFAULT_HOST = "localhost"

CONF_HOST = "host"
CONF_PORT = "port"

API_BASE = "/api/v1"

# Polling interval (seconds) — fallback when WebSocket is unavailable
POLL_INTERVAL = 10

# WebSocket reconnect delay bounds (seconds)
WS_RECONNECT_MIN = 1
WS_RECONNECT_MAX = 30
