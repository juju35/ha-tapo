# Changelog

## 1.1.0 (2026-11-11)

- Privacy mode: the camera shows a large crossed-out camera instead of a black or frozen picture; the live stream stops and comes back when privacy mode is turned off. The camera entity stays on, with a `privacy_mode` attribute
- Stills taken from the running stream only when the stream integration is loaded; otherwise one shared FFmpeg snapshot

## 1.0.0 (2026-11-11)

First release.

- One camera entity per camera, with a stream quality select (HD or SD) that switches the running stream; on/off is the privacy mode
- Detection sensors (motion, person, vehicle, pet, line crossing, tamper, baby crying, barking, meowing, glass break, package) created at setup from what the camera supports, fed by an ONVIF event subscription that is renewed and recreated on its own, with a safety timeout and a `tapo_cameras_event` event
- One request at a time per camera and one light batched request per refresh (unused requests left out, slow ones every 10 minutes); last good answer kept for 10 minutes when a request fails; changes shown at once and confirmed by a debounced refresh; backoff after a failed login, re-authentication on a wrong password
- Snapshots: one FFmpeg at a time per camera, stills reused for 5 s; dead ONVIF connections detected
- Switches, selects, numbers, buttons, siren, lights, sensors and firmware update entity for the camera's settings
- Pan/tilt and preset actions, DHCP discovery, reconfigure, diagnostics
- 23 languages
