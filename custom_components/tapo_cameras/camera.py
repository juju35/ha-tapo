"""Camera: one entity, its RTSP stream in the quality chosen with the "stream quality" select.

On/off is the privacy mode.
"""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any
from urllib.parse import quote

from homeassistant.components.camera import Camera, CameraEntityDescription, CameraEntityFeature
from homeassistant.components.ffmpeg import async_get_image
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform, service
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TapoConfigEntry
from .const import (
    ATTR_NAME,
    ATTR_PAN,
    ATTR_PRESET,
    ATTR_TILT,
    CONF_EXTRA_FFMPEG_ARGS,
    CONF_RTSP_TRANSPORT,
    DEFAULT_RTSP_PORT,
    DEFAULT_RTSP_TRANSPORT,
    SNAPSHOT_CACHE,
    STREAM_PATHS,
)
from .coordinator import TapoCoordinator
from .entity import TapoEntity
from .model import TapoData, is_on

PARALLEL_UPDATES = 0

PRIVACY = ("getLensMaskConfig", "lens_mask", "lens_mask_info", "enabled")


# The device's main entity: named after the camera.
CAMERA = CameraEntityDescription(key="camera", name=None)


def _privacy(data: TapoData) -> bool | None:
    return is_on(data.get(*PRIVACY))


class TapoCamera(TapoEntity, Camera):
    _attr_supported_features = CameraEntityFeature.STREAM | CameraEntityFeature.ON_OFF
    # A frame of a running stream instead of a new RTSP connection: the camera allows only two.
    _attr_use_stream_for_stills = True
    _attr_brand = "TP-Link"

    def __init__(self, coordinator: TapoCoordinator) -> None:
        TapoEntity.__init__(self, coordinator, CAMERA)
        Camera.__init__(self)
        entry = coordinator.config_entry
        user = quote(entry.data[CONF_USERNAME], safe="")
        password = quote(entry.data[CONF_PASSWORD], safe="")
        self._base_url = f"rtsp://{user}:{password}@{entry.data[CONF_HOST]}:{DEFAULT_RTSP_PORT}/"
        self._quality = coordinator.stream_quality
        self._snapshot_lock = asyncio.Lock()
        self._snapshot: tuple[tuple[str, int | None, int | None], float, bytes] | None = None
        self._extra_arguments: str = entry.options.get(CONF_EXTRA_FFMPEG_ARGS, "")
        self.stream_options[CONF_RTSP_TRANSPORT] = entry.options.get(CONF_RTSP_TRANSPORT, DEFAULT_RTSP_TRANSPORT)

    @property
    def _url(self) -> str:
        return self._base_url + STREAM_PATHS[self.coordinator.stream_quality]

    @callback
    def _handle_coordinator_update(self) -> None:
        # The quality changed: a running stream switches to the other one.
        if self._quality != self.coordinator.stream_quality:
            self._quality = self.coordinator.stream_quality
            if self.stream is not None and self.is_on:
                self.stream.update_source(self._url)
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"stream_quality": self.coordinator.stream_quality}

    @property
    def model(self) -> str | None:
        return self.data.basic_info.get("device_model")

    @property
    def is_on(self) -> bool:
        return not _privacy(self.data)

    @property
    def motion_detection_enabled(self) -> bool:
        return bool(is_on(self.data.get("getDetectionConfig", "motion_detection", "motion_det", "enabled")))

    async def stream_source(self) -> str | None:
        return self._url if self.is_on else None

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        """A still from ffmpeg, when no stream is running (otherwise Home Assistant takes it from the stream).

        Dashboards ask every few seconds, often several at once: one ffmpeg at a time, and a still
        taken less than SNAPSHOT_CACHE ago is served again, so that stills don't use up the camera's
        two RTSP sessions.
        """
        if not self.is_on:
            return None
        key = (self._url, width, height)
        async with self._snapshot_lock:
            cached = self._snapshot
            if cached is not None and cached[0] == key and monotonic() - cached[1] < SNAPSHOT_CACHE:
                return cached[2]
            image = await async_get_image(
                self.hass, self._url, extra_cmd=self._extra_arguments or None, width=width, height=height
            )
            self._snapshot = (key, monotonic(), image) if image else None
            return image

    async def _async_set_privacy(self, enabled: bool) -> None:
        await self.coordinator.async_command(
            lambda tapo: tapo.setPrivacyMode(enabled),
            apply=lambda data: data.set(PRIVACY[0], PRIVACY[1:], "on" if enabled else "off"),
        )

    async def async_turn_on(self) -> None:
        await self._async_set_privacy(False)

    async def async_turn_off(self) -> None:
        await self._async_set_privacy(True)

    async def async_enable_motion_detection(self) -> None:
        await self._async_set_motion(True)

    async def async_disable_motion_detection(self) -> None:
        await self._async_set_motion(False)

    async def _async_set_motion(self, enabled: bool) -> None:
        await self.coordinator.async_command(
            lambda tapo: tapo.setMotionDetection(enabled),
            apply=lambda data: data.set(
                "getDetectionConfig", ("motion_detection", "motion_det", "enabled"), "on" if enabled else "off"
            ),
        )

    # Entity actions (registered in __init__.py)

    async def async_ptz(self, **kwargs: Any) -> None:
        pan, tilt = round(kwargs.get(ATTR_PAN, 0)), round(kwargs.get(ATTR_TILT, 0))
        await self.coordinator.async_command(lambda tapo: tapo.moveMotor(pan, tilt), retry=False)

    async def async_go_to_preset(self, **kwargs: Any) -> None:
        preset = self._preset_id(kwargs[ATTR_PRESET])
        await self.coordinator.async_command(lambda tapo: tapo.setPreset(preset), retry=False)

    async def async_save_preset(self, **kwargs: Any) -> None:
        name = kwargs[ATTR_NAME]
        await self.coordinator.async_command(lambda tapo: tapo.savePreset(name), retry=False)

    async def async_delete_preset(self, **kwargs: Any) -> None:
        preset = self._preset_id(kwargs[ATTR_PRESET])
        await self.coordinator.async_command(lambda tapo: tapo.deletePreset(preset), retry=False)

    def _preset_id(self, preset: str) -> str:
        """A preset given by name or by id."""
        preset = str(preset)
        presets = self.data.presets
        if preset in presets:
            return preset
        return next((pid for pid, name in presets.items() if name == preset), preset)


async def async_setup_entry(
    hass: HomeAssistant, entry: TapoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([TapoCamera(coordinator)])
    if not hasattr(service, "async_register_platform_entity_service"):
        from . import ENTITY_SERVICES  # noqa: PLC0415

        platform = entity_platform.async_get_current_platform()
        for name, (schema, method) in ENTITY_SERVICES.items():
            platform.async_register_entity_service(name, schema, method)
