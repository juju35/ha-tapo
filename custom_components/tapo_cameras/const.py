"""Constants for Tapo Cameras."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "tapo_cameras"
VERSION: Final = "1.0.0"

CONF_CLOUD_PASSWORD: Final = "cloud_password"
CONF_CONTROL_PORT: Final = "control_port"
CONF_RTSP_TRANSPORT: Final = "rtsp_transport"
CONF_MOTION_TIMEOUT: Final = "motion_timeout"
CONF_ONVIF_EVENTS: Final = "onvif_events"
CONF_EXTRA_FFMPEG_ARGS: Final = "extra_ffmpeg_arguments"

DEFAULT_CONTROL_PORT: Final = 443
DEFAULT_ONVIF_PORT: Final = 2020
DEFAULT_RTSP_PORT: Final = 554
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 600
DEFAULT_MOTION_TIMEOUT: Final = 60
DEFAULT_RTSP_TRANSPORT: Final = "tcp"
RTSP_TRANSPORTS: Final = ["tcp", "udp", "udp_multicast", "http"]
# Stream quality → RTSP path.
STREAM_PATHS: Final = {"hd": "stream1", "sd": "stream2"}
DEFAULT_STREAM_QUALITY: Final = "hd"

# Control requests: the camera account is for RTSP/ONVIF, the control API logs in as "admin"
# with the password of the Tapo account (cloud password).
CONTROL_USER: Final = "admin"

# A write is confirmed by a refresh shortly after, once the camera has applied it.
REFRESH_AFTER_WRITE: Final = 2.0
# Timeout of one request to the camera (the library has no timeout of its own on every path).
REQUEST_TIMEOUT: Final = 20.0
# Login is rate limited by the camera: after a failure, wait before connecting again.
RECONNECT_BACKOFF: Final = (10, 30, 60, 120, 300)

# ONVIF pull point events.
ONVIF_PULL_TIMEOUT: Final = timedelta(seconds=20)
ONVIF_MESSAGE_LIMIT: Final = 100
ONVIF_RETRY_BACKOFF: Final = (5, 15, 30, 60, 120, 300)
ONVIF_SUBSCRIPTION_TTL: Final = timedelta(minutes=10)

EVENT_TAPO: Final = f"{DOMAIN}_event"

SERVICE_PTZ: Final = "ptz"
SERVICE_SAVE_PRESET: Final = "save_preset"
SERVICE_DELETE_PRESET: Final = "delete_preset"
SERVICE_GO_TO_PRESET: Final = "go_to_preset"

ATTR_PAN: Final = "pan"
ATTR_TILT: Final = "tilt"
ATTR_PRESET: Final = "preset"
ATTR_NAME: Final = "name"

DEFAULT_MOVE_ANGLE: Final = 15
