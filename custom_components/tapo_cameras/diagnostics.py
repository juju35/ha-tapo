"""Diagnostics: entry, the camera's answers and the event subscription, without secrets."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import TapoConfigEntry
from .const import CONF_CLOUD_PASSWORD

TO_REDACT = {
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_CLOUD_PASSWORD,
    "mac",
    "ssid",
    "ipaddr",
    "gateway",
    "dns",
    "ip",
    "dev_id",
    "hw_id",
    "oem_id",
    "device_alias",
    "latitude",
    "longitude",
    "bssid",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: TapoConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "klap": coordinator.client.is_klap,
        "last_update_success": coordinator.last_update_success,
        "logins": coordinator.client.logins,
        # Requests whose last good answer is kept while they fail.
        "failing": sorted(coordinator.failing),
        "unsupported": sorted(coordinator.unsupported),
        "state": async_redact_data(coordinator.data.raw if coordinator.data else {}, TO_REDACT),
        "events": coordinator.events.as_dict() if coordinator.events else None,
    }
