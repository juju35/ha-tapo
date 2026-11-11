"""Every translation has exactly the keys and placeholders of the English one."""

from __future__ import annotations

import json
import re
import string
from pathlib import Path

import pytest

TRANSLATIONS = Path(__file__).parent.parent / "custom_components" / "tapo_cameras" / "translations"
LANGUAGES = [
    "bg",
    "cs",
    "da",
    "de",
    "el",
    "es",
    "fr",
    "hu",
    "it",
    "lv",
    "nl",
    "pl",
    "pt",
    "pt-BR",
    "ro",
    "ru",
    "sk",
    "sl",
    "sr",
    "sr-Latn",
    "sv",
    "uk",
]


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, path))
        else:
            flat[path] = value
    return flat


def _load(language: str) -> dict[str, str]:
    return _flatten(json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8")))


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def test_all_languages_are_tested():
    """A new translations/*.json file is added to LANGUAGES."""
    assert sorted(p.stem for p in TRANSLATIONS.glob("*.json")) == sorted(["en", *LANGUAGES])


@pytest.mark.parametrize("language", LANGUAGES)
def test_translation_parity(language: str):
    """Same keys as en.json (but entity names), same placeholders in each string, nothing empty."""
    english, other = _load("en"), _load(language)
    english = {key: text for key, text in english.items() if not key.startswith("entity.")}
    assert sorted(other) == sorted(english)
    for key, text in english.items():
        assert other[key].strip(), key
        assert _placeholders(other[key]) == _placeholders(text), key


# Serbian: brands, placeholders and identifiers stay in Latin script in the Cyrillic translation.
_SR_LATIN_ALLOWED = re.compile(r"TP-Link|Tapo|ONVIF|FFmpeg|RTSP|TCP|UDP|HTTP|Wi-Fi|LED|HD|SD|IP|ID|Hz|\{\w+\}")


@pytest.mark.parametrize(
    ("language", "forbidden"),
    [("sr", r"[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f]"), ("sr-Latn", r"[\u0400-\u04ff]")],
)
def test_serbian_script(language: str, forbidden: str):
    """No Latin letter in sr (but brands and placeholders), no Cyrillic letter in sr-Latn."""
    for key, text in _load(language).items():
        assert not re.search(forbidden, _SR_LATIN_ALLOWED.sub("", text)), key


@pytest.mark.parametrize("language", LANGUAGES)
def test_entity_names_not_translated(language: str):
    """Entity names (and their states) stay in English in every language: same names, same entity IDs."""
    data = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
    assert "entity" not in data


def test_every_translation_key_is_used() -> None:
    """Each entity translation key of en.json belongs to an entity, and the other way round."""
    from custom_components.tapo_cameras import (
        binary_sensor,
        button,
        light,
        media_player,
        number,
        select,
        sensor,
        siren,
        switch,
    )

    english = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))["entity"]
    used = {
        "binary_sensor": {*binary_sensor.DETECTIONS, "detection", binary_sensor.SUBSCRIPTION.translation_key},
        "button": {d.translation_key for d in button.BUTTONS if d.translation_key},
        "light": {d.translation_key for d in light.LIGHTS},
        "media_player": {media_player.SPEAKER.translation_key},
        "number": {d.translation_key for d in number.NUMBERS} | {number.MOVE_ANGLE.translation_key},
        "select": {
            d.translation_key for d in (*select.DETECTIONS, *select.MODES, select.PRESET, select.STREAM_QUALITY)
        },
        "sensor": {d.translation_key for d in sensor.SENSORS if d.translation_key},
        "siren": {siren.SIREN.translation_key},
        "switch": {d.translation_key for d in switch.SWITCHES} | {"smart_track", "alarm_trigger"},
    }
    assert {platform: set(keys) for platform, keys in english.items()} == used
