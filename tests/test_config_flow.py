"""Config, reauth, reconfigure, discovery and options flows."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tapo_cameras.const import (
    CONF_CLOUD_PASSWORD,
    CONF_CONTROL_PORT,
    CONF_EXTRA_FFMPEG_ARGS,
    CONF_MOTION_TIMEOUT,
    CONF_ONVIF_EVENTS,
    CONF_RTSP_TRANSPORT,
    DOMAIN,
)

from .conftest import ENTRY_DATA, FakeCamera

USER_INPUT = {**ENTRY_DATA, CONF_CONTROL_PORT: 443}


async def test_user_flow(hass: HomeAssistant, camera: FakeCamera) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: " 192.168.1.15 "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living room"
    assert result["data"][CONF_HOST] == "192.168.1.15"
    assert result["result"].unique_id == "aa:bb:cc:dd:ee:ff"


async def test_user_flow_errors(hass: HomeAssistant, camera: FakeCamera) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    for error, expected in (
        (Exception("Invalid authentication data"), {CONF_CLOUD_PASSWORD: "invalid_auth"}),
        (Exception("Temporary Suspension: Try again in 60 seconds"), {"base": "suspended"}),
        (OSError("No route to host"), {"base": "cannot_connect"}),
    ):
        camera.constructor.side_effect = error
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == expected
    camera.constructor.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_already_configured_updates_host(hass: HomeAssistant, camera: FakeCamera, entry: MockConfigEntry) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "192.168.1.99"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "192.168.1.99"


async def test_dhcp_discovery(hass: HomeAssistant, camera: FakeCamera) -> None:
    info = DhcpServiceInfo(ip="192.168.1.42", hostname="c225_eeff", macaddress="aabbccddeeff")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=info)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "192.168.1.42"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_dhcp_known_camera_moved(hass: HomeAssistant, camera: FakeCamera, entry: MockConfigEntry) -> None:
    info = DhcpServiceInfo(ip="192.168.1.77", hostname="c225_eeff", macaddress="aabbccddeeff")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=info)
    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_HOST] == "192.168.1.77"


async def test_reauth(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    result = await loaded.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    camera.constructor.side_effect = Exception("Invalid authentication data")
    new = {CONF_CLOUD_PASSWORD: "new-cloud", "username": "camuser", "password": "new-cam"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    assert result["errors"] == {CONF_CLOUD_PASSWORD: "invalid_auth"}
    camera.constructor.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    # The entry reloads with the new password: let it finish before checking and tearing down.
    await hass.async_block_till_done()
    assert loaded.data[CONF_CLOUD_PASSWORD] == "new-cloud"


async def test_reconfigure_wrong_camera(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    result = await loaded.start_reconfigure_flow(hass)
    camera.tapo.basicInfo = {"device_info": {"basic_info": {"mac": "11-22-33-44-55-66"}}}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "192.168.1.50"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_camera"
    assert loaded.data[CONF_HOST] == "192.168.1.15"


async def test_options(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    options = {
        CONF_SCAN_INTERVAL: 60,
        CONF_ONVIF_EVENTS: False,
        CONF_MOTION_TIMEOUT: 30,
        CONF_RTSP_TRANSPORT: "udp",
        CONF_EXTRA_FFMPEG_ARGS: "",
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], options)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert loaded.options[CONF_SCAN_INTERVAL] == 60
    assert loaded.runtime_data.update_interval.total_seconds() == 60
