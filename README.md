# ha-tapo

[![Marketplace](https://img.shields.io/badge/Marketplace-Custom-41BDF5.svg)](https://www.home-assistant.io/integrations/marketplace/)
[![Marketplace Validation](https://github.com/juju35/ha-tapo/actions/workflows/hacs.yml/badge.svg)](https://github.com/juju35/ha-tapo/actions/workflows/hacs.yml)
[![Validate](https://github.com/juju35/ha-tapo/actions/workflows/validate.yml/badge.svg)](https://github.com/juju35/ha-tapo/actions/workflows/validate.yml)
[![Lint](https://github.com/juju35/ha-tapo/actions/workflows/lint.yml/badge.svg)](https://github.com/juju35/ha-tapo/actions/workflows/lint.yml)
[![Release](https://img.shields.io/github/v/release/juju35/ha-tapo)](https://github.com/juju35/ha-tapo/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/juju35/ha-tapo/blob/main/LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/julienstep9)

<p align="center"><img src="https://raw.githubusercontent.com/juju35/ha-tapo/main/custom_components/tapo_cameras/brand/icon.png" alt="Tapo Cameras" width="120"></p>

Home Assistant integration for TP-Link Tapo cameras, fully local: live stream, privacy mode, pan/tilt and presets, detection settings, and motion, person, vehicle, pet… sensors that exist from the start and come back on their own after a camera reboot.

[![Open your Home Assistant instance and open a repository inside the Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=juju35&repository=ha-tapo&category=integration)

## Features

- **One camera entity** per camera, with a **Stream quality** select (HD or SD) that switches the running stream; turning the camera off turns privacy mode on
- **Privacy mode shown**: the camera displays a large crossed-out camera instead of a black or frozen picture, and its live stream stops until privacy mode is turned off
- **Detection sensors created at setup**, for every detection the camera supports (motion, person, vehicle, pet, line crossing, tamper, baby crying, barking, meowing, glass break, package), before any event happens; a detection the camera reports and this integration doesn't know yet gets a sensor too
- **Events that survive reboots**: the camera's ONVIF event subscription is renewed before it expires and created again, with a backoff, when the camera drops it; a **Detection events** sensor shows whether the subscription is up
- **Safety timeout**: a detection still on after 60 s without news (configurable) is switched off, for firmwares that never send the end of an event
- **One request at a time** per camera: Tapo firmwares drop the session when two requests arrive together, so polling and changes share a queue
- **One light request per refresh**: the settings are read with a single batched request, without the half of it this integration never uses; capabilities, network, SD card and presets are read every 10 minutes, after a change and after a new login only
- **No flapping**: a setting the camera refuses for a moment (privacy mode, busy camera) keeps its last value for up to 10 minutes instead of turning its entity unavailable
- **Snapshots shared**: one FFmpeg at a time per camera, a still reused for 5 s, and stills taken from the running stream when there is one, so dashboards don't use up the camera's two RTSP sessions
- **Dead event connections detected**: a pull without any answer 15 s past its timeout restarts the subscription; an empty answer arriving at once is not pulled again for a second
- **Changes shown at once**, then confirmed by a refresh 2 s later; several changes in a row (sliders, moves) end in one refresh
- **No login storms**: after a failed login the integration waits (10 s, 30 s… up to 5 min) instead of hitting a camera that locks itself after too many attempts; a wrong password opens the **re-authentication** flow
- **Entities follow what the camera answers**: an unsupported setting gets no entity
- Switches: privacy mode, status LED, notifications, rich notifications, audio recording, microphone mute, noise cancelling, lens distortion correction, flip, auto track, smart track per target, privacy zones, recording to SD card, loop recording, line crossing detection, scheduled reboot, automatic firmware upgrade, diagnose mode, and which detections trigger the alarm (disabled by default)
- Selects: motion, person, vehicle, pet, package, baby crying, barking, meowing, glass break and tamper detection (off / low / normal / high), night vision, day/night mode, light frequency, presets, stream quality
- Numbers: speaker and microphone volume, motion sensitivity, spotlight intensity, step of the move buttons
- Buttons: reboot, move up / down / left / right, calibrate, format SD card (disabled by default)
- **Speaker**: a media player that plays sounds, files and text-to-speech on the camera, over its two-way audio channel; its volume is the camera's speaker volume
- Siren (the camera's alarm), spotlight and floodlight lights, firmware update entity
- Sensors: Wi-Fi signal, SD card status, free space and size; Wi-Fi network, connection type and IP address (disabled by default)
- Actions to pan/tilt by an angle and to go to, save or delete a preset
- **DHCP discovery**, and a camera that changes address is followed by its MAC address
- **Reconfigure** (address, accounts) without removing the camera
- **Diagnostics** with personal data redacted
- English, French, German, Spanish, Italian, Dutch, Portuguese (European and Brazilian), Polish, Serbian (Cyrillic and Latin), Romanian, Danish, Swedish, Bulgarian, Russian, Ukrainian, Hungarian, Slovak, Czech, Slovenian, Latvian and Greek

## Prerequisites

- Home Assistant 2025.8 or newer
- In the Tapo app: **Third-Party Compatibility** turned on (under **Me**), and a **camera account** created in the camera's **Advanced Settings → Camera Account**
- From Home Assistant, the camera must be reachable on ports **443** (settings), **554** (RTSP stream), **2020** (ONVIF events) and **8800** (speaker). These are local ports: never forward them on your router
- Use only one integration per camera: the camera accepts few simultaneous connections

## Installation

### Via the Marketplace (recommended)

Click the button below to add the repository directly:

[![Add to the Marketplace](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=juju35&repository=ha-tapo&category=integration)

Then click **Install** and restart Home Assistant.

Or manually:

1. Open **Settings → Marketplace → Add from link** (top right; this needs a GitHub account connected)
2. Add `https://github.com/juju35/ha-tapo` — Type: **Integration**
3. Open **Tapo Cameras** and click **Install**
4. Restart Home Assistant

### Manual

Copy `custom_components/tapo_cameras/` to `/config/custom_components/tapo_cameras/`, then restart Home Assistant.

## Configuration

**Settings → Devices & services → Add integration → Tapo Cameras**, or accept the discovered camera.

| Field | Description |
|---|---|
| Host | IP address of the camera (give it a fixed address in your router) |
| Tapo account password | Password of the TP-Link account the camera is added to: used for the settings |
| Camera account username / password | The camera account created in the app: used for the stream and the detection events |
| Control port | 443 for cameras and doorbells |

### Options

| Option | Default | Description |
|---|---|---|
| Refresh interval | 30 s | How often the settings are read. Detections are pushed by the camera, whatever this interval |
| Detection events | on | Detection sensors from the camera's ONVIF events |
| Detection safety timeout | 60 s | A detection without news for this long is switched off; 0 to wait for the camera |
| RTSP transport | TCP | TCP, UDP, UDP multicast or HTTP |
| Extra FFmpeg arguments | — | Added to the FFmpeg command that takes snapshots |

## Entities

The camera entity is named after the camera; the others are named after what they control (`switch.living_room_privacy_mode`, `binary_sensor.living_room_person`…).

| Entity | Notes |
|---|---|
| `camera.<name>` | Stream in the quality of `select.<name>_stream_quality`; turn on/off = privacy mode; in privacy mode, no live stream and a crossed-out camera as picture; attributes `stream_quality`, `privacy_mode` |
| `binary_sensor.<name>_motion`, `_person`, `_vehicle`… | From the event subscription; unavailable only while it is down; attribute `last_change` |
| `binary_sensor.<name>_detection_events` | Subscription state; attributes `last_error`, `messages` |
| `select.<name>_<type>_detection` | `off`, `low`, `normal`, `high` |
| `media_player.<name>_speaker` | Plays on the camera's speaker (`media_player.play_media`, `tts.speak`, media browser); `playing` while it talks; volume = speaker volume |
| `select.<name>_preset` | Moves to the chosen preset; the state stays unknown (the camera has no current preset) |
| `number.<name>_move_step` | Degrees of the move buttons (15 by default), kept by Home Assistant |

### Talking through the camera

```yaml
action: tts.speak
target:
  entity_id: tts.google_translate_en_com
data:
  media_player_entity_id: media_player.living_room_speaker
  message: Someone is at the door
```

Any audio Home Assistant can read works too (`media_player.play_media` with a media-source item or a URL). The audio is converted by FFmpeg to the camera's format (G.711 A-law, 8 kHz mono) and sent in real time; a new sound replaces the one playing. Not possible while privacy mode is on.

### Event `tapo_cameras_event`

Fired when a detection starts:

```yaml
trigger:
  - trigger: event
    event_type: tapo_cameras_event
    event_data:
      type: person
action:
  - action: notify.mobile_app_phone
    data:
      message: "Someone at {{ trigger.event.data.host }}"
```

Data: `device_id`, `host`, `type` (`motion`, `person`, `vehicle`, `pet`, `line_crossing`, `tamper`, `baby_cry`, `bark`, `meow`, `glass_break`, `package`, `area_intrusion`, or the name the camera gives a new kind of detection).

### Actions

All target a camera entity.

```yaml
action: tapo_cameras.ptz
target:
  entity_id: camera.living_room
data:
  pan: 30     # degrees to the right, negative to the left
  tilt: -10   # degrees up, negative down
```

```yaml
action: tapo_cameras.go_to_preset   # also save_preset (field: name) and delete_preset
target:
  entity_id: camera.living_room
data:
  preset: Door   # name or ID
```

## How it works

- Settings: the camera's local API on port 443, signed in as `admin` with the Tapo account password (the camera's own rule), through the `pytapo` library. Every refresh is one batched request (unused requests left out, slow ones every 10 minutes); every call goes through one queue per camera, run in the executor; a request that timed out is not retried at once, as it may still be running
- Stream: RTSP on port 554 with the camera account (`stream1` = HD, `stream2` = SD). Snapshots are taken from the running stream when there is one, so they don't use one of the camera's two stream slots
- Speaker: the camera's media port 8800 (the one of its own app), signed in with the Tapo account password; a "talk" session receiving G.711 A-law in an MPEG transport stream, paced in real time
- Detections: ONVIF pull point on port 2020 with the camera account, pulled every 20 s at most (the camera answers as soon as something happens), subscription renewed before it expires

## Development

```bash
pip install -r requirements_test.txt && pytest
pre-commit run --all-files
```

### Releasing

1. Bump the version in `custom_components/tapo_cameras/manifest.json` and `const.py` (`VERSION`)
2. Add a `## <version>` section at the top of [CHANGELOG.md](https://github.com/juju35/ha-tapo/blob/main/CHANGELOG.md)
3. Push to `main`: the **Release** workflow creates the tag and the GitHub release with the changelog section as notes

## Translations

The configuration, options, actions and error messages follow the language of Home Assistant. Entity names (and select states) stay in English in every language, so that names and entity IDs are the same everywhere. Currently supported:

| Language | Code |
|---|---|
| English | `en` |
| Français | `fr` |
| Deutsch | `de` |
| Español | `es` |
| Italiano | `it` |
| Nederlands | `nl` |
| Português | `pt` |
| Português (Brasil) | `pt-BR` |
| Polski | `pl` |
| Română | `ro` |
| Dansk | `da` |
| Svenska | `sv` |
| Български | `bg` |
| Русский | `ru` |
| Українська | `uk` |
| Magyar | `hu` |
| Slovenčina | `sk` |
| Čeština | `cs` |
| Slovenščina | `sl` |
| Latviešu | `lv` |
| Ελληνικά | `el` |
| Српски | `sr` |
| Srpski (latinica) | `sr-Latn` |

Contributions for additional languages are welcome!

## License

[MIT](https://github.com/juju35/ha-tapo/blob/main/LICENSE)

## Support

If you find this project useful, you can support its development:

<a href="https://buymeacoffee.com/julienstep9"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" height="50"></a>
