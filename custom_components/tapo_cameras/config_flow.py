"""Configuration: one entry per camera, identified by its MAC address."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytapo import Tapo

from .api import TapoAuthError, TapoSuspendedError, classify
from .const import (
    CONF_CLOUD_PASSWORD,
    CONF_CONTROL_PORT,
    CONF_EXTRA_FFMPEG_ARGS,
    CONF_MOTION_TIMEOUT,
    CONF_ONVIF_EVENTS,
    CONF_RTSP_TRANSPORT,
    CONTROL_USER,
    DEFAULT_CONTROL_PORT,
    DEFAULT_MOTION_TIMEOUT,
    DEFAULT_RTSP_TRANSPORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    RTSP_TRANSPORTS,
)
from .model import dig

_LOGGER = logging.getLogger(__name__)

_PASSWORD = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


class CannotConnect(Exception):
    """The camera did not answer."""


def _probe(hass: HomeAssistant, host: str, cloud_password: str, port: int) -> dict[str, Any]:
    """Log in and read the device information (blocking)."""
    tapo = Tapo(
        host, CONTROL_USER, cloud_password, cloud_password, controlPort=port, printWarnInformation=False, hass=hass
    )
    try:
        info = tapo.basicInfo
        return dig(info, "device_info", "basic_info") or info
    finally:
        try:
            tapo.close()
        except Exception:  # noqa: BLE001 - closing is best effort
            _LOGGER.debug("Closing the probe session of %s failed", host, exc_info=True)


async def async_probe(hass: HomeAssistant, host: str, cloud_password: str, port: int) -> dict[str, Any]:
    """Device information; raises TapoAuthError, TapoSuspendedError or CannotConnect."""
    try:
        return await hass.async_add_executor_job(_probe, hass, host, cloud_password, port)
    except Exception as err:
        error = classify(err)
        if isinstance(error, (TapoAuthError, TapoSuspendedError)):
            raise error from err
        raise CannotConnect(str(err)) from err


def _errors_for(err: Exception) -> dict[str, str]:
    if isinstance(err, TapoAuthError):
        return {CONF_CLOUD_PASSWORD: "invalid_auth"}
    if isinstance(err, TapoSuspendedError):
        return {"base": "suspended"}
    return {"base": "cannot_connect"}


def _camera_schema(defaults: Mapping[str, Any], with_host: bool = True) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_host:
        fields[vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED))] = str
    fields.update(
        {
            vol.Required(CONF_CLOUD_PASSWORD): _PASSWORD,
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, vol.UNDEFINED)): str,
            vol.Required(CONF_PASSWORD): _PASSWORD,
        }
    )
    if with_host:
        fields[vol.Optional(CONF_CONTROL_PORT, default=defaults.get(CONF_CONTROL_PORT, DEFAULT_CONTROL_PORT))] = (
            vol.All(vol.Coerce(int), vol.Range(min=1, max=65535))
        )
    return vol.Schema(fields)


class TapoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> TapoOptionsFlow:
        return TapoOptionsFlow()

    async def _async_try(
        self, host: str, user_input: Mapping[str, Any], port: int
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Device information of the camera with these credentials, or the form errors."""
        try:
            return await async_probe(self.hass, host, user_input[CONF_CLOUD_PASSWORD], port), {}
        except (TapoAuthError, TapoSuspendedError, CannotConnect) as err:
            return None, _errors_for(err)

    async def _async_try_form(self, user_input: dict[str, Any]) -> tuple[str, dict[str, Any] | None, dict[str, str]]:
        """The camera of a form with a host: its host, information (unique ID set from its MAC) or errors."""
        host = user_input[CONF_HOST].strip()
        info, errors = await self._async_try(host, user_input, user_input.get(CONF_CONTROL_PORT, DEFAULT_CONTROL_PORT))
        if info is not None and (mac := info.get("mac")):
            await self.async_set_unique_id(format_mac(mac.replace("-", ":")))
        return host, info, errors

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host, info, errors = await self._async_try_form(user_input)
            if info is not None:
                if self.unique_id:
                    self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                title = info.get("device_alias") or info.get("device_model") or host
                return self.async_create_entry(title=title, data={**user_input, CONF_HOST: host})
        defaults = user_input or ({CONF_HOST: self._host} if self._host else {})
        return self.async_show_form(step_id="user", data_schema=_camera_schema(defaults), errors=errors)

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        await self.async_set_unique_id(format_mac(discovery_info.macaddress))
        # A camera that moved to another address keeps working.
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})
        self._host = discovery_info.ip
        self.context["title_placeholders"] = {"name": discovery_info.hostname or discovery_info.ip}
        return await self.async_step_user()

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            info, errors = await self._async_try(
                entry.data[CONF_HOST], user_input, entry.data.get(CONF_CONTROL_PORT, DEFAULT_CONTROL_PORT)
            )
            if info is not None:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_camera_schema(entry.data, with_host=False),
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host, info, errors = await self._async_try_form(user_input)
            if info is not None:
                if self.unique_id and entry.unique_id:
                    self._abort_if_unique_id_mismatch(reason="wrong_camera")
                return self.async_update_reload_and_abort(entry, data_updates={**user_input, CONF_HOST: host})
        return self.async_show_form(step_id="reconfigure", data_schema=_camera_schema(entry.data), errors=errors)


class TapoOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
                vol.Required(CONF_ONVIF_EVENTS, default=options.get(CONF_ONVIF_EVENTS, True)): bool,
                vol.Required(
                    CONF_MOTION_TIMEOUT, default=options.get(CONF_MOTION_TIMEOUT, DEFAULT_MOTION_TIMEOUT)
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
                vol.Required(
                    CONF_RTSP_TRANSPORT, default=options.get(CONF_RTSP_TRANSPORT, DEFAULT_RTSP_TRANSPORT)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=RTSP_TRANSPORTS, translation_key=CONF_RTSP_TRANSPORT)
                ),
                vol.Optional(
                    CONF_EXTRA_FFMPEG_ARGS,
                    description={"suggested_value": options.get(CONF_EXTRA_FFMPEG_ARGS, "")},
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
