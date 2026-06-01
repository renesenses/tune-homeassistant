"""Data coordinator for Tune Music Server."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import API_BASE, DOMAIN, POLL_INTERVAL, WS_RECONNECT_MAX, WS_RECONNECT_MIN

_LOGGER = logging.getLogger(__name__)


class TuneCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls Tune server and optionally uses WebSocket."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.host = entry.data[CONF_HOST]
        self.port = entry.data[CONF_PORT]
        self.base_url = f"http://{self.host}:{self.port}{API_BASE}"
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ws_task: asyncio.Task | None = None
        self._shutdown = False

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=asyncio.timedelta(seconds=POLL_INTERVAL) if POLL_INTERVAL else None,
        )

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._session

    async def api_get(self, path: str) -> Any:
        """GET request to the Tune API."""
        async with self.session.get(f"{self.base_url}{path}") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def api_post(self, path: str, data: dict | None = None) -> Any:
        """POST request to the Tune API."""
        async with self.session.post(
            f"{self.base_url}{path}", json=data or {}
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def api_patch(self, path: str, data: dict) -> Any:
        """PATCH request to the Tune API."""
        async with self.session.patch(
            f"{self.base_url}{path}", json=data
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch zones + playback state from Tune."""
        try:
            zones = await self.api_get("/zones")
            now_listening = await self.api_get("/playback/now-listening")

            zone_states = {}
            zone_list = zones if isinstance(zones, list) else zones.get("zones", [])
            for z in zone_list:
                zid = z.get("id")
                if zid is None:
                    continue
                zone_states[zid] = z

            for nl in (now_listening if isinstance(now_listening, list) else []):
                zid = nl.get("zone_id")
                if zid and zid in zone_states:
                    zone_states[zid].update(nl)

            return {"zones": zone_states}
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Cannot reach Tune server: {err}") from err

    async def async_config_entry_first_refresh(self) -> None:
        """First refresh + start WebSocket listener."""
        await super().async_config_entry_first_refresh()
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def _ws_loop(self) -> None:
        """WebSocket listener with auto-reconnect."""
        delay = WS_RECONNECT_MIN
        while not self._shutdown:
            try:
                ws_url = f"ws://{self.host}:{self.port}/ws"
                self._ws = await self.session.ws_connect(ws_url)
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
                        elif event_type.startswith("playback.") or event_type.startswith("zone."):
                            await self.async_request_refresh()
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break

            except (aiohttp.ClientError, asyncio.CancelledError) as err:
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
            asyncio.create_task(self._ws.close())
        if self._session and not self._session.closed:
            asyncio.create_task(self._session.close())
