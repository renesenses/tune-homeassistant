# Tune Music Server — Home Assistant Integration

Control [Tune](https://github.com/renesenses/tune-server-rust) from Home Assistant. Each Tune zone appears as a `media_player` entity with full playback control, media browsing, and real-time state updates via WebSocket.

## Features

- **Play / Pause / Stop / Next / Previous / Seek** — full transport control
- **Volume & Mute** — per-zone volume control
- **Media Browser** — browse albums, artists, genres, playlists, radio stations
- **Play Media** — play albums, tracks, or playlists from the HA UI
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
3. Enter the host and port of your Tune server (default: `localhost:8888`)
4. Your Tune zones will appear as media_player entities

## Voice Control Examples

Once configured, you can control Tune via any voice assistant connected to HA:

- *"Hey Siri, pause the music in the living room"*
- *"Alexa, next track on Tune Salon"*
- *"Hey Google, set volume to 50% on Tune"*

## Requirements

- Tune Server v0.8.0+
- Home Assistant 2024.1.0+
