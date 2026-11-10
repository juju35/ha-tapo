"""Tapo Cameras: local control of TP-Link Tapo cameras."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import service
from homeassistant.helpers.typing import ConfigType

from .api import TapoClient
from .const import (
    ATTR_NAME,
    ATTR_PAN,
    ATTR_PRESET,
    ATTR_TILT,
    CONF_CLOUD_PASSWORD,
    CONF_CONTROL_PORT,
    CONF_MOTION_TIMEOUT,
    CONF_ONVIF_EVENTS,
    DEFAULT_CONTROL_PORT,
    DEFAULT_MOTION_TIMEOUT,
    DEFAULT_ONVIF_PORT,
    DOMAIN,
    SERVICE_DELETE_PRESET,
    SERVICE_GO_TO_PRESET,
    SERVICE_PTZ,
    SERVICE_SAVE_PRESET,
)
from .coordinator import TapoCoordinator
from .events import OnvifEvents

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SIREN,
    Platform.SWITCH,
    Platform.UPDATE,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type TapoConfigEntry = ConfigEntry[TapoCoordinator]

_ANGLE = vol.All(vol.Coerce(float), vol.Range(min=-360, max=360))
_PRESET = vol.All(cv.string, vol.Length(min=1))
ENTITY_SERVICES = {
    SERVICE_PTZ: ({vol.Optional(ATTR_PAN, default=0): _ANGLE, vol.Optional(ATTR_TILT, default=0): _ANGLE}, "async_ptz"),
    SERVICE_GO_TO_PRESET: ({vol.Required(ATTR_PRESET): _PRESET}, "async_go_to_preset"),
    SERVICE_SAVE_PRESET: ({vol.Required(ATTR_NAME): _PRESET}, "async_save_preset"),
    SERVICE_DELETE_PRESET: ({vol.Required(ATTR_PRESET): _PRESET}, "async_delete_preset"),
}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the camera actions (pan/tilt and presets)."""
    # Home Assistant before 2025.10: registered by the camera platform instead (camera.py).
    if hasattr(service, "async_register_platform_entity_service"):
        for name, (schema, method) in ENTITY_SERVICES.items():
            service.async_register_platform_entity_service(
                hass, DOMAIN, name, entity_domain=Platform.CAMERA, schema=schema, func=method
            )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TapoConfigEntry) -> bool:
    data, options = entry.data, entry.options
    client = TapoClient(
        hass, data[CONF_HOST], data[CONF_CLOUD_PASSWORD], data.get(CONF_CONTROL_PORT, DEFAULT_CONTROL_PORT)
    )
    coordinator = TapoCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.async_close()
        raise

    if options.get(CONF_ONVIF_EVENTS, True) and data.get(CONF_USERNAME):
        coordinator.events = OnvifEvents(
            hass,
            data[CONF_HOST],
            DEFAULT_ONVIF_PORT,
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            options.get(CONF_MOTION_TIMEOUT, DEFAULT_MOTION_TIMEOUT),
            lambda: _device_id(hass, entry),
        )
        coordinator.events.async_start()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _device_id(hass: HomeAssistant, entry: TapoConfigEntry) -> str | None:
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.unique_id or entry.entry_id)})
    return device.id if device else None


async def async_unload_entry(hass: HomeAssistant, entry: TapoConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = entry.runtime_data
        if coordinator.events is not None:
            coordinator.events.async_stop()
        await coordinator.client.async_close()
    return unloaded
