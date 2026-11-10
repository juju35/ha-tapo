"""Camera state: the answers of one batched request, read through paths.

The camera answers a single `multipleRequest` with every setting it supports. Each answer is
kept as returned (`raw[method][index]`, `None` for a method the camera does not support), and
entities read their value through a path in it. A feature is supported when its path resolves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

Path = tuple[str | int, ...]

ON_VALUES = frozenset({"on", "1", 1})

# Detection sensitivities: the camera stores a percentage, the app shows three levels.
SENSITIVITY_PERCENT = {"low": 20, "normal": 50, "high": 80}
SENSITIVITY_OPTIONS = ["off", "low", "normal", "high"]

_SIZE = re.compile(r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[KMGT]?i?B)\s*$", re.IGNORECASE)
_UNIT_BYTES = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}


def dig(obj: Any, *path: str | int) -> Any:
    """Follow `path` through dicts (keys) and lists (indexes); None when a step is missing."""
    for key in path:
        if isinstance(obj, dict):
            obj = obj.get(key)
        elif isinstance(obj, list) and isinstance(key, int) and -len(obj) <= key < len(obj):
            obj = obj[key]
        else:
            return None
        if obj is None:
            return None
    return obj


def is_on(value: Any) -> bool | None:
    """'on'/'off' (and the 1/0 some firmwares use) to a bool; None when unknown."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.lower()
    return value in ON_VALUES


def on_off(value: bool) -> str:
    return "on" if value else "off"


def sensitivity_level(value: Any) -> str | None:
    """A percentage (or a label) to low / normal / high."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip().lstrip("-").isdigit():
        label = value.strip().lower()
        return {"medium": "normal", "middle": "normal"}.get(label, label if label in SENSITIVITY_PERCENT else None)
    percent = int(value)
    if percent <= 35:
        return "low"
    if percent <= 65:
        return "normal"
    return "high"


def size_in_bytes(value: Any) -> float | None:
    """'29.7GB', '512MB'… to bytes; None when not a size."""
    if not isinstance(value, str) or not (match := _SIZE.match(value)):
        return None
    unit = match["unit"].upper().replace("I", "")
    return float(match["value"]) * _UNIT_BYTES[unit]


@dataclass(slots=True)
class TapoData:
    """Answers of the camera to the batched request."""

    raw: dict[str, list[Any]] = field(default_factory=dict)

    def get(self, method: str, *path: str | int, index: int = 0) -> Any:
        answers = self.raw.get(method)
        if not answers or index >= len(answers) or not answers[index]:
            return None
        return dig(answers[index], *path)

    def has(self, method: str, *path: str | int, index: int = 0) -> bool:
        return self.get(method, *path, index=index) is not None

    def set(self, method: str, path: Path, value: Any, index: int = 0) -> None:
        """Write `value` at `path`, after a successful change, until the next refresh confirms it."""
        answers = self.raw.get(method)
        if not answers or index >= len(answers) or not isinstance(answers[index], dict):
            return
        node = answers[index]
        for key in path[:-1]:
            nxt = node.get(key) if isinstance(node, dict) else None
            if not isinstance(nxt, dict):
                return
            node = nxt
        node[path[-1]] = value

    # Device

    @property
    def basic_info(self) -> dict[str, Any]:
        return self.get("getDeviceInfo", "device_info", "basic_info") or {}

    @property
    def mac(self) -> str | None:
        mac = self.basic_info.get("mac")
        return mac.replace("-", ":").lower() if isinstance(mac, str) else None

    # Pan / tilt

    @property
    def ptz(self) -> bool:
        """Pan/tilt camera: only those answer the preset, patrol and tracking requests."""
        return any(self.get(m) is not None for m in ("getPresetConfig", "getPatrolAction", "getTargetTrackConfig"))

    @property
    def presets(self) -> dict[str, str]:
        """Preset id → name."""
        preset = self.get("getPresetConfig", "preset", "preset") or {}
        ids, names = preset.get("id") or [], preset.get("name") or []
        return {str(pid): str(name) for pid, name in zip(ids, names, strict=False)}

    # Storage

    @property
    def disks(self) -> list[dict[str, Any]]:
        disks = []
        for item in self.get("getSdCardStatus", "harddisk_manage", "hd_info") or []:
            if isinstance(item, dict):
                info = next((v for v in item.values() if isinstance(v, dict)), None)
                if info:
                    disks.append(info)
        return disks

    # Network

    @property
    def connection(self) -> dict[str, Any]:
        return self.get("getConnectionType") or {}

    # Alarm events that can trigger the camera's alarm

    @property
    def alarm_event_types(self) -> dict[str, bool]:
        types = self.get("getAlertEventType", "msg_alarm", "msg_alarm_type") or []
        return {
            item["name"]: bool(is_on(item.get("enabled")))
            for item in types
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }

    @property
    def smart_track(self) -> dict[str, bool]:
        info = self.get("getSmartTrackConfig", "smart_track", "smart_track_info") or {}
        return {key: bool(is_on(value)) for key, value in info.items() if is_on(value) is not None}

    def set_alarm_event_type(self, name: str, enabled: bool) -> None:
        for item in self.get("getAlertEventType", "msg_alarm", "msg_alarm_type") or []:
            if isinstance(item, dict) and item.get("name") == name:
                item["enabled"] = on_off(enabled)
