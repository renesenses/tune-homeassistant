"""Data coordinator for Tune Music Server."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import re
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

# Artwork: content hash as stored by the server (`is_hex_hash`), size caps.
_HEX_HASH = re.compile(r"^(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{64})$")
ARTWORK_MAX_BYTES = 10 * 1024 * 1024
THUMBNAIL_MAX_BYTES = 5 * 1024 * 1024
THUMBNAIL_SIZE = 200  # one of the server's buckets (80, 128, 200, 400)


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

    async def fetch_artwork(
        self, url: str, size: int | None = None, max_bytes: int = ARTWORK_MAX_BYTES
    ) -> tuple[bytes | None, str | None]:
        """Artwork bytes, following the server's redirects by hand.

        `/library/albums/{id}/artwork` answers a redirect: to
        `/api/v1/library/artwork/{hash}` (kept on the Tune server, with the
        API key and the thumbnail `size`), or to a provider URL (fetched
        without the Tune credentials). The body is capped at `max_bytes`.
        """
        for _ in range(3):
            internal = url.startswith(self.server_url + "/")
            params = {"size": str(size)} if size and internal and "/library/artwork/" in url else None
            async with self.session.get(
                url,
                params=params,
                headers=self.headers if internal else None,
                timeout=self._timeout,
                allow_redirects=False,
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location", "")
                    if location.startswith("/"):
                        url = self.server_url + location
                    elif location.startswith(("http://", "https://")):
                        url = location
                    else:
                        return None, None
                    continue
                if resp.status != 200:
                    return None, None
                declared = resp.headers.get("Content-Length", "")
                if declared.isdigit() and int(declared) > max_bytes:
                    return None, None
                data = bytearray()
                async for chunk in resp.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        return None, None
                return bytes(data), resp.headers.get("Content-Type")
        return None, None

    def artwork_url(self, cover: str | None, album_id: int | str | None) -> str | None:
        """Where the server serves a cover, from what it stores in `cover_path`.

        Mirrors `pochette_de_l_album` (tune-server `routes/library/artwork.rs`):
        `cover_path` is a provider URL, a 32/64-hex content hash, or (older
        rows) a file path that only the album route can resolve.
        """
        if cover and cover.startswith(("http://", "https://")):
            return cover
        if cover and _HEX_HASH.match(cover):
            return f"{self.base_url}/library/artwork/{cover}"
        if album_id is not None and str(album_id).isdigit():
            return f"{self.base_url}/library/albums/{album_id}/artwork"
        return None

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
