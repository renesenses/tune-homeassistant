# Tune Music Server — Home Assistant Integration

Control [Tune](https://github.com/renesenses/tune-server-rust) from Home Assistant. Each Tune zone appears as a `media_player` entity with full playback control, media browsing, and real-time state updates via WebSocket.

## Features

- **Play / Pause / Stop / Next / Previous / Seek** — full transport control
- **Volume & Mute** — per-zone volume control
- **Media Browser** — browse albums, artists, genres, playlists, radio stations
- **Play Media** — play albums, tracks, playlists or radio stations from the HA UI
- **Shuffle & Repeat** — per-zone
- **Real-time updates** — WebSocket push for instant state changes
- **Multi-zone** — each Tune zone is a separate media_player entity
- **Voice control** — works with Alexa, Google Assistant, Siri (via HomeKit bridge), and HA Assist

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → **Custom Repositories**
3. Add `renesenses/tune-homeassistant` as an **Integration**
4. Install "Tune Music Server"
5. Restart Home Assistant

### Manual

Copy `custom_components/tune/` to your HA `config/custom_components/` directory.

## Setup

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Tune Music Server"
3. Enter the host and port of your Tune server (default: `localhost:8888`) — or accept the server discovered automatically on your network (zeroconf `_tune-server._tcp`)
4. **API key**: leave empty unless authentication is enabled on your Tune server. If it is, create an API key as an administrator (`POST /api/v1/auth/api-key`) and paste it here; if authentication is enabled later, Home Assistant asks for the key (re-authentication).
5. Your Tune zones will appear as media_player entities (zones created later appear after reloading the integration)

Use the server's IP address or its `.local` name: a fully qualified host name (e.g. `tune.example.com`) is refused by the Tune server (HTTP 421) unless it is listed in `TUNE_ALLOWED_HOSTS` on the server.

## Notes

- Volume: Tune caps a single volume increase at +10 dB (speaker and hearing protection). A large jump requested from Home Assistant (or Siri) may land below the requested level; repeat the command to go further.
- HomeKit / Siri: expose the Tune `media_player` entities through the HomeKit Bridge integration (HomeKit shows them as TV-like accessories or switches, depending on the HomeKit Bridge mode).

## Voice Control Examples

Once configured, you can control Tune via any voice assistant connected to HA:

- *"Hey Siri, pause the music in the living room"*
- *"Alexa, next track on Tune Salon"*
- *"Hey Google, set volume to 50% on Tune"*

## Requirements

- Tune Server v1.0.0-rc12 or later (playback routes under `/api/v1/zones/{id}/…`)
- Home Assistant 2024.11.0 or later
