# Changelog

## 1.0.0 (2026-11-11)

First release.

- One camera entity per camera, with a stream quality select (HD or SD) that switches the running stream; on/off is the privacy mode
- Detection sensors (motion, person, vehicle, pet, line crossing, tamper, baby crying, barking, meowing, glass break, package) created at setup from what the camera supports, fed by an ONVIF event subscription that is renewed and recreated on its own, with a safety timeout and a `tapo_cameras_event` event
- One request at a time per camera and one batched request per refresh; changes shown at once and confirmed by a debounced refresh; backoff after a failed login, re-authentication on a wrong password
- Switches, selects, numbers, buttons, siren, lights, sensors and firmware update entity for the camera's settings
- Pan/tilt and preset actions, DHCP discovery, reconfigure, diagnostics
- 23 languages
