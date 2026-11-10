# Tapo Cameras — Agent Context

## Purpose
Home Assistant custom integration for TP-Link Tapo cameras, fully local: settings through the camera's control API (`pytapo`), video through RTSP, detections through an ONVIF pull point subscription.

## Architecture

```
custom_components/tapo_cameras/
├── __init__.py      # Entry setup: TapoClient + TapoCoordinator, first refresh, OnvifEvents (option onvif_events + camera account), platforms; camera actions (ptz, go_to/save/delete_preset) registered in async_setup with service.async_register_platform_entity_service, by camera.py before HA 2025.10
├── api.py           # TapoClient: one asyncio.Lock per camera (firmwares drop the session on concurrent requests), calls in the executor with REQUEST_TIMEOUT, getMost() = every setting in one request (retried without getAudioConfig), one reconnect on a lost session (not for retry=False nor after a timeout, the request may still run in its thread), login backoff RECONNECT_BACKOFF or the camera's own "Temporary Suspension" delay; classify() maps the library's bare Exceptions to TapoAuthError / TapoSuspendedError / TapoPrivacyModeError / TapoConnectionError / TapoError (camera answered: session kept)
├── coordinator.py   # DataUpdateCoordinator[TapoData]: omits UNUSED_METHODS always and SLOW_METHODS except on a full refresh (setup, FULL_REFRESH_INTERVAL, after a command, after a new login: client.logins); _merge keeps omitted answers and, answer by answer, the last good one of a failing request for STALE_ANSWER_LIMIT; auth error → ConfigEntryAuthFailed; async_command(func, apply, retry) = write, apply to the state at once, debounced refresh (REFRESH_AFTER_WRITE); device_info; move_angle and stream_quality kept here for the entities that share them
├── model.py         # TapoData: raw getMost answers (method → [answer or False]), get(method, *path, index), set() for optimistic writes; helpers is_on, on_off, sensitivity_level (percent or label → low/normal/high), size_in_bytes; ptz, presets, disks, connection, alarm_event_types, smart_track
├── events.py        # OnvifEvents: background task, subscribe (ONVIFCamera port 2020 + create_pullpoint_manager), PullMessages loop (wait_for ONVIF_PULL_TIMEOUT + ONVIF_PULL_GRACE: no answer = dead connection; empty instant answers paced by ONVIF_MIN_PULL_INTERVAL) until the manager reports the subscription lost, backoff ONVIF_RETRY_BACKOFF (_backoff, patched in tests); parse_message() → (key, active) from SimpleItem names (EVENT_ITEMS, unknown "Is…" → snake_case key, topic fallback EVENT_TOPICS); states cleared when the subscription is lost; motion_timeout safety off; fires tapo_cameras_event on each start
├── entity.py        # TapoEntity (unique_id = <mac>_<key>), TapoDescriptionMixin (method + path; supported = path resolves, or supported_fn), TapoDescribedEntity (unavailable when its value is missing)
├── camera.py        # One entity (name None): snapshots single-flight + SNAPSHOT_CACHE; rtsp://user:pass@host:554/stream1|stream2 by coordinator.stream_quality, switched with stream.update_source on change; on/off = privacy; snapshots via ffmpeg, use_stream_for_stills
├── binary_sensor.py # Detections from events (DETECTIONS: device class + request telling support), created at setup; new keys seen in events get a sensor; event_subscription connectivity sensor
├── switch.py / select.py / number.py / button.py / light.py / siren.py / sensor.py / update.py  # Descriptions with method/path + pytapo setter
├── config_flow.py   # user (host, cloud_password, camera account, control_port), dhcp, reauth_confirm, reconfigure (abort wrong_camera on another MAC); options (scan_interval, onvif_events, motion_timeout, rtsp_transport, extra_ffmpeg_arguments) with OptionsFlowWithReload
├── diagnostics.py   # Entry, raw state and events, redacted
└── const.py / manifest.json / services.yaml / icons.json / translations/*.json / brand/
```

## Rules
- Never call pytapo from the event loop: it is synchronous, and with `hass` given it schedules its own coroutines on the loop and waits for them.
- A new getMost request read by an entity must not be in UNUSED_METHODS; put it in SLOW_METHODS if it rarely changes.
- Every request goes through `TapoClient.async_call` (the lock). Actions that must not run twice if their answer is lost (moves, presets, reboot, alarm, firmware) use `retry=False`.
- A new setting = a description: `method` from the getMost list (pytapo `getMost`), `path` into its answer, setter calling the pytapo setter, `to_raw` for the optimistic write. Add its translation key to en.json and every language (tests/test_translations.py checks keys are used and equal everywhere).
- Control login: user `admin` + Tapo account password (cloud password) for both password arguments; RTSP/ONVIF: the camera account.

## Release
Bump `version` in manifest.json and `VERSION` in const.py, add the CHANGELOG.md section; pushing to main publishes `vX.Y.Z` with `tapo_cameras.zip`.

## Tests
`pip install -r requirements_test.txt && pytest`. The library is replaced by `FakeCamera` (tests/conftest.py, state from tests/fixtures/c225.json); ONVIF is blocked by the autouse `no_onvif` fixture and faked in tests/test_events.py. CI also runs the suite on HA 2025.8.0 (minimum in hacs.json). `no_deprecated_calls` fails a test on any deprecation report naming the integration.
