"""Tune integration against the API of the Tune server (v1.0.0-rc12 / rc13).

Payloads mirror what the server answers (captured from a rc12 binary).
"""
from homeassistant import config_entries
from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from ipaddress import ip_address
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tune.const import CONF_API_KEY, DOMAIN

BASE = "http://192.168.1.50:8888/api/v1"

ZONES = [
    {
        "id": 1,
        "name": "Salon",
        "state": "playing",
        "volume": 0.3,
        "muted": False,
        "shuffle": True,
        "repeat": "all",
        "position_ms": 1000,
        "current_track": {
            "id": 1,
            "title": "Piste 1",
            "artist_name": "Artiste",
            "album_title": "Album",
            "cover_path": "abc123",
            "duration_ms": 20000,
        },
    }
]


def _mock_server(aioclient_mock, zones_status=200):
    aioclient_mock.get(f"{BASE}/system/version", json={"version": "1.0.0-rc12", "engine": "rust"})
    aioclient_mock.get(f"{BASE}/zones", json=ZONES, status=zones_status)
    for action in ("pause", "resume", "stop", "next", "previous", "seek", "volume", "shuffle", "repeat", "play"):
        aioclient_mock.post(f"{BASE}/zones/1/{action}", json={})
    aioclient_mock.put(f"{BASE}/zones/1/muted", status=204)
    aioclient_mock.post(f"{BASE}/radios/7/play/1", json={})
    aioclient_mock.get(
        f"{BASE}/library/albums?limit=200",
        json={"items": [{"id": 1, "title": "Album", "cover_path": "abc123"}], "total": 1},
    )
    aioclient_mock.get(
        f"{BASE}/library/artists?limit=200",
        json={"items": [{"id": 1, "name": "Artiste"}], "total": 1},
    )


def _calls(aioclient_mock):
    return [(m, str(u)) for m, u, _d, _h in aioclient_mock.mock_calls]


async def test_user_flow(hass, aioclient_mock):
    _mock_server(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("custom_components.tune.async_setup_entry", _ok)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_PORT: 8888}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Tune 1.0.0-rc12"
    assert result["data"] == {CONF_HOST: "192.168.1.50", CONF_PORT: 8888}


async def test_user_flow_auth_required(hass, aioclient_mock):
    _mock_server(aioclient_mock, zones_status=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_PORT: 8888}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_zeroconf_flow(hass, aioclient_mock):
    _mock_server(aioclient_mock)
    info = ZeroconfServiceInfo(
        ip_address=ip_address("192.168.1.50"),
        ip_addresses=[ip_address("192.168.1.50")],
        hostname="shrek.local.",
        name="Tune._tune-server._tcp.local.",
        port=8888,
        type="_tune-server._tcp.local.",
        properties={"version": "1.0.0-rc12", "path": "/api/v1"},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("custom_components.tune.async_setup_entry", _ok)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "192.168.1.50", CONF_PORT: 8888}


async def _ok(hass, entry):
    return True


async def _setup(hass, aioclient_mock, data=None):
    _mock_server(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN, data=data or {CONF_HOST: "192.168.1.50", CONF_PORT: 8888},
        unique_id="tune_192.168.1.50_8888",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entity_state(hass, aioclient_mock, no_websocket):
    entry = await _setup(hass, aioclient_mock)
    assert entry.state is ConfigEntryState.LOADED
    state = hass.states.get("media_player.tune_server_192_168_1_50_salon")
    assert state is not None, hass.states.async_entity_ids()
    assert state.state == "playing"
    assert state.attributes["media_title"] == "Piste 1"
    assert state.attributes["media_artist"] == "Artiste"
    assert state.attributes["media_album_name"] == "Album"
    assert state.attributes["media_duration"] == 20
    assert state.attributes["volume_level"] == 0.3
    assert state.attributes["shuffle"] is True
    assert state.attributes["repeat"] == "all"


async def test_services_hit_zone_routes(hass, aioclient_mock, no_websocket):
    await _setup(hass, aioclient_mock)
    eid = "media_player.tune_server_192_168_1_50_salon"
    aioclient_mock.mock_calls.clear()
    for service, extra in (
        ("media_pause", {}),
        ("media_play", {}),
        ("media_next_track", {}),
        ("media_previous_track", {}),
        ("media_stop", {}),
        ("media_seek", {"seek_position": 12}),
        ("volume_set", {"volume_level": 0.5}),
        ("volume_mute", {"is_volume_muted": True}),
        ("shuffle_set", {"shuffle": False}),
        ("repeat_set", {"repeat": "one"}),
        ("play_media", {"media_content_type": "album", "media_content_id": "1"}),
        ("play_media", {"media_content_type": "channel", "media_content_id": "7"}),
    ):
        await hass.services.async_call(MP_DOMAIN, service, {"entity_id": eid, **extra}, blocking=True)
    calls = [c for c in _calls(aioclient_mock) if not c[1].endswith("/zones")]
    assert calls == [
        ("POST", f"{BASE}/zones/1/pause"),
        ("POST", f"{BASE}/zones/1/resume"),
        ("POST", f"{BASE}/zones/1/next"),
        ("POST", f"{BASE}/zones/1/previous"),
        ("POST", f"{BASE}/zones/1/stop"),
        ("POST", f"{BASE}/zones/1/seek"),
        ("POST", f"{BASE}/zones/1/volume"),
        ("PUT", f"{BASE}/zones/1/muted"),
        ("POST", f"{BASE}/zones/1/shuffle?enabled=false"),
        ("POST", f"{BASE}/zones/1/repeat?mode=one"),
        ("POST", f"{BASE}/zones/1/play"),
        ("POST", f"{BASE}/radios/7/play/1"),
    ]
    bodies = {str(u): d for _m, u, d, _h in aioclient_mock.mock_calls}
    assert bodies[f"{BASE}/zones/1/seek"] == {"position_ms": 12000}
    assert bodies[f"{BASE}/zones/1/volume"] == {"volume": 0.5}
    assert bodies[f"{BASE}/zones/1/muted"] == {"muted": True}
    assert bodies[f"{BASE}/zones/1/play"] == {"album_id": 1}


async def test_api_key_header(hass, aioclient_mock, no_websocket):
    await _setup(hass, aioclient_mock, {CONF_HOST: "192.168.1.50", CONF_PORT: 8888, CONF_API_KEY: "s3cret"})
    headers = [h for _m, u, _d, h in aioclient_mock.mock_calls if str(u).endswith("/zones")]
    assert headers and headers[0]["Authorization"] == "ApiKey s3cret"


async def test_auth_failure_starts_reauth(hass, aioclient_mock, no_websocket):
    _mock_server(aioclient_mock, zones_status=401)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "192.168.1.50", CONF_PORT: 8888})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == config_entries.SOURCE_REAUTH for f in flows)


async def test_browse_library(hass, aioclient_mock, no_websocket):
    await _setup(hass, aioclient_mock)
    entity = hass.data["entity_components"][MP_DOMAIN].get_entity(
        "media_player.tune_server_192_168_1_50_salon"
    )
    albums = await entity.async_browse_media("album", "albums")
    assert [c.title for c in albums.children] == ["Album"]
    assert albums.children[0].thumbnail == f"{BASE}/library/artwork/abc123"
    artists = await entity.async_browse_media("artist", "artists")
    assert [c.title for c in artists.children] == ["Artiste"]
