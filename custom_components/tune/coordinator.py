"""Data coordinator for Tune Music Server."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_BASE,
    CONF_API_KEY,
    DOMAIN,
    POLL_INTERVAL,
    WS_RECONNECT_MAX,
    WS_RECONNECT_MIN,
    auth_headers,
    url_host,
)

_LOGGER = logging.getLogger(__name__)


async def _json_or_none(resp: aiohttp.ClientResponse) -> Any:
    """Body of a command response: some routes answer 204 No Content."""
    if resp.status == 204 or resp.content_type != "application/json":
        return None
    return await resp.json()


# High-rate events (VU meters, position ticks): no state refresh for them.
_IGNORED_EVENTS = ("playback.audio_levels", "playback.position")


class TuneCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls Tune server and optionally uses WebSocket."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.host = entry.data[CONF_HOST]
        self.port = entry.data[CONF_PORT]
        self.server_url = f"http://{url_host(self.host)}:{self.port}"
        self.base_url = f"{self.server_url}{API_BASE}"
        self._entry = entry
        self.headers = auth_headers(entry.data.get(CONF_API_KEY))
        self.session = async_get_clientsession(hass)
        self._timeout = aiohttp.ClientTimeout(total=10)
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ws_task: asyncio.Task | None = None
        self._shutdown = False

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=POLL_INTERVAL) if POLL_INTERVAL else None,
        )

    async def api_get(self, path: str) -> Any:
        """GET request to the Tune API."""
        async with self.session.get(
            f"{self.base_url}{path}", headers=self.headers, timeout=self._timeout
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def api_post(
        self, path: str, data: dict | None = None, params: dict | None = None
    ) -> Any:
        """POST request to the Tune API."""
        async with self.session.post(
            f"{self.base_url}{path}",
            json=data or {},
            params=params,
            headers=self.headers,
            timeout=self._timeout,
        ) as resp:
            resp.raise_for_status()
            return await _json_or_none(resp)

    async def api_put(self, path: str, data: dict) -> Any:
        """PUT request to the Tune API."""
        async with self.session.put(
            f"{self.base_url}{path}", json=data, headers=self.headers, timeout=self._timeout
        ) as resp:
            resp.raise_for_status()
            return await _json_or_none(resp)

    async def api_get_all(self, path: str, key: str, page: int = 500, cap: int = 5000) -> list:
        """Every item of a paginated list route (`limit` / `offset`), up to `cap`."""
        items: list = []
        sep = "&" if "?" in path else "?"
        while len(items) < cap:
            data = await self.api_get(f"{path}{sep}limit={page}&offset={len(items)}")
            if isinstance(data, list):
                chunk, total = data, None
            elif isinstance(data, dict):
                chunk = data.get("items") or data.get(key) or []
                total = data.get("total")
            else:
                break
            items.extend(chunk)
            if len(chunk) < page or (total is not None and len(items) >= total):
                break
        return items[:cap]

    async def api_get_bytes(self, url: str) -> tuple[bytes | None, str | None]:
        """GET raw bytes (artwork) with the Tune credentials."""
        async with self.session.get(
            url, headers=self.headers, timeout=self._timeout
        ) as resp:
            if resp.status != 200:
                return None, None
            return await resp.read(), resp.headers.get("Content-Type")

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch zones (with their playback state) from Tune.

        `GET /zones` carries each zone's `state`, `current_track`,
        `position_ms`, `volume`, `muted`, `shuffle` and `repeat`.
        """
        try:
            zones = await self.api_get("/zones")
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                raise ConfigEntryAuthFailed(
                    "Tune server requires an API key"
                ) from err
            raise UpdateFailed(f"Tune server error: {err}") from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Cannot reach Tune server: {err}") from err

        zone_list = zones if isinstance(zones, list) else zones.get("zones", [])
        zone_states = {z["id"]: z for z in zone_list if z.get("id") is not None}
        return {"zones": zone_states, "updated_at": dt_util.utcnow()}

    async def async_config_entry_first_refresh(self) -> None:
        """First refresh + start WebSocket listener."""
        await super().async_config_entry_first_refresh()
        self._ws_task = self._entry.async_create_background_task(
            self.hass, self._ws_loop(), name="tune_websocket"
        )

    async def _ws_loop(self) -> None:
        """WebSocket listener with auto-reconnect."""
        delay = WS_RECONNECT_MIN
        while not self._shutdown:
            try:
                ws_url = f"ws://{url_host(self.host)}:{self.port}/ws"
                self._ws = await self.session.ws_connect(
                    ws_url, headers=self.headers, heartbeat=30
                )
                _LOGGER.info("Tune WebSocket connected")
                delay = WS_RECONNECT_MIN

                await self._ws.send_json({
                    "action": "subscribe",
                    "patterns": ["playback.*", "zone.*"],
                })

                async for msg in self._ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = msg.json()
                        event_type = data.get("type", "")
                        if event_type == "ping":
                            await self._ws.send_str("pong")
                        elif event_type in _IGNORED_EVENTS:
                            continue
                        elif event_type.startswith(("playback.", "zone.")):
                            await self.async_request_refresh()
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break

            except asyncio.CancelledError:
                return
            except aiohttp.WSServerHandshakeError as err:
                if err.status in (401, 403):
                    # Authentication enabled (or key revoked) on the server:
                    # ask for a key instead of retrying forever.
                    _LOGGER.warning("Tune WebSocket refused (HTTP %s): reauthentication needed", err.status)
                    self._entry.async_start_reauth(self.hass)
                    return
                _LOGGER.debug("Tune WebSocket handshake failed: %s", err)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                if self._shutdown:
                    return
                _LOGGER.debug("Tune WebSocket disconnected: %s", err)
            except Exception:
                _LOGGER.exception("Tune WebSocket unexpected error")

            if self._shutdown:
                return
            _LOGGER.debug("Tune WebSocket reconnecting in %ss", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, WS_RECONNECT_MAX)

    def shutdown(self) -> None:
        """Stop WebSocket and close session."""
        self._shutdown = True
        if self._ws_task:
            self._ws_task.cancel()
        if self._ws and not self._ws.closed:
            self.hass.async_create_task(self._ws.close())
