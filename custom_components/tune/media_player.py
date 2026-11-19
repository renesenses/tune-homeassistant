"""Media player entity for Tune Music Server zones."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .browse_media import async_browse_media
from .const import DOMAIN
from .coordinator import TuneCoordinator

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.REPEAT_SET
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Tune media player from a config entry."""
    coordinator: TuneCoordinator = hass.data[DOMAIN][entry.entry_id]
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]

    entities = []
    for zone_id, zone_data in coordinator.data.get("zones", {}).items():
        entities.append(TuneMediaPlayer(coordinator, zone_id, zone_data, host, port))

    async_add_entities(entities, update_before_add=False)


class TuneMediaPlayer(CoordinatorEntity[TuneCoordinator], MediaPlayerEntity):
    """Representation of a Tune zone as a media player."""

    _attr_has_entity_name = True
    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(
        self,
        coordinator: TuneCoordinator,
        zone_id: int,
        zone_data: dict,
        host: str,
        port: int,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._host = host
        self._port = port
        self._attr_unique_id = f"tune_{host}_{port}_zone_{zone_id}"
        self._attr_name = zone_data.get("name", f"Zone {zone_id}")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{host}:{port}")},
            "name": f"Tune Server ({host})",
            "manufacturer": "Tune",
            "model": "Music Server",
        }

    @property
    def _zone(self) -> dict:
        """Get current zone data from coordinator."""
        return self.coordinator.data.get("zones", {}).get(self._zone_id, {})

    @property
    def state(self) -> MediaPlayerState:
        """Return the current state."""
        s = self._zone.get("state", "stopped")
        if s == "playing":
            return MediaPlayerState.PLAYING
        if s == "paused":
            return MediaPlayerState.PAUSED
        return MediaPlayerState.IDLE

    @property
    def _track(self) -> dict | None:
        """The track the zone is playing (`current_track` in `GET /zones`)."""
        return self._zone.get("current_track") or self._zone.get("now_playing")

    @property
    def media_content_type(self) -> MediaType:
        return MediaType.MUSIC

    @property
    def media_title(self) -> str | None:
        np = self._track
        return np.get("title") if np else None

    @property
    def media_artist(self) -> str | None:
        np = self._track
        return np.get("artist_name") if np else None

    @property
    def media_album_name(self) -> str | None:
        np = self._track
        return np.get("album_title") if np else None

    @property
    def media_image_url(self) -> str | None:
        np = self._track
        cover = np.get("cover_path") if np else None
        if not cover:
            return None
        if cover.startswith(("http://", "https://")):
            return cover
        return f"{self.coordinator.base_url}/library/artwork/{cover}"

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """Fetch the artwork with the Tune credentials (API key if set)."""
        url = self.media_image_url
        if not url:
            return None, None
        if not url.startswith(self.coordinator.base_url):
            return await super().async_get_media_image()
        return await self.coordinator.api_get_bytes(url)

    @property
    def media_duration(self) -> int | None:
        np = self._track
        ms = (np or {}).get("duration_ms") or self._zone.get("duration_ms")
        return ms // 1000 if ms else None

    @property
    def media_position(self) -> int | None:
        ms = self._zone.get("position_ms")
        return ms // 1000 if ms is not None else None

    @property
    def media_position_updated_at(self):
        return self.coordinator.data.get("updated_at")

    @property
    def volume_level(self) -> float | None:
        return self._zone.get("volume")

    @property
    def is_volume_muted(self) -> bool | None:
        return self._zone.get("muted")

    @property
    def shuffle(self) -> bool | None:
        return self._zone.get("shuffle")

    @property
    def repeat(self) -> RepeatMode | None:
        mode = self._zone.get("repeat")
        try:
            return RepeatMode(mode) if mode else None
        except ValueError:
            return None

    async def _command(self, action: str, data: dict | None = None, params: dict | None = None) -> None:
        await self.coordinator.api_post(
            f"/zones/{self._zone_id}/{action}", data, params=params
        )
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        await self._command("resume")

    async def async_media_pause(self) -> None:
        await self._command("pause")

    async def async_media_stop(self) -> None:
        await self._command("stop")

    async def async_media_next_track(self) -> None:
        await self._command("next")

    async def async_media_previous_track(self) -> None:
        await self._command("previous")

    async def async_media_seek(self, position: float) -> None:
        await self._command("seek", {"position_ms": int(position * 1000)})

    async def async_set_volume_level(self, volume: float) -> None:
        # Tune caps a single increase at +10 dB unless `confirm_increase`
        # is sent (hearing / speaker protection): a large jump may land
        # below the requested level. We keep that safety on purpose.
        await self._command("volume", {"volume": volume})

    async def async_mute_volume(self, mute: bool) -> None:
        await self.coordinator.api_put(f"/zones/{self._zone_id}/muted", {"muted": mute})
        await self.coordinator.async_request_refresh()

    async def async_set_shuffle(self, shuffle: bool) -> None:
        # Tune reads `enabled` from the query string, not the body.
        await self._command("shuffle", params={"enabled": "true" if shuffle else "false"})

    async def async_set_repeat(self, repeat: RepeatMode | str) -> None:
        # Tune reads `mode` (off / one / all) from the query string.
        await self._command("repeat", params={"mode": str(getattr(repeat, "value", repeat))})

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Play a specific media item."""
        if media_type == MediaType.CHANNEL:
            # Radio station: dedicated route.
            await self.coordinator.api_post(f"/radios/{int(media_id)}/play/{self._zone_id}")
            await self.coordinator.async_request_refresh()
            return

        body: dict[str, Any] = {}
        if media_type == MediaType.ALBUM:
            body["album_id"] = int(media_id)
        elif media_type == MediaType.PLAYLIST:
            body["playlist_id"] = int(media_id)
        else:
            body["track_id"] = int(media_id)

        await self._command("play", body)

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Implement the media browser."""
        return await async_browse_media(
            self.coordinator, self._zone_id, media_content_type, media_content_id
        )
