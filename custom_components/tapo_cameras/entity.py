"""Base entity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import TapoCoordinator
from .model import Path, TapoData


@dataclass(frozen=True, kw_only=True)
class TapoDescriptionMixin:
    """Where an entity reads its value: answer of `method`, at `path`."""

    method: str = ""
    path: Path = ()
    # The entity exists when this returns True for the first state (default: the path resolves).
    supported_fn: Callable[[TapoData], bool] | None = None

    def raw_value(self, data: TapoData) -> Any:
        return data.get(self.method, *self.path)

    def supported(self, data: TapoData) -> bool:
        if self.supported_fn is not None:
            return self.supported_fn(data)
        return self.raw_value(data) is not None


class TapoEntity(CoordinatorEntity[TapoCoordinator]):
    """Entity of one camera."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TapoCoordinator, description: EntityDescription, key: str | None = None) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        base = coordinator.config_entry.unique_id or coordinator.config_entry.entry_id
        self._attr_unique_id = f"{base}_{key or description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def data(self) -> TapoData:
        return self.coordinator.data


class TapoDescribedEntity(TapoEntity):
    """Entity reading its value through a `TapoDescriptionMixin` description."""

    entity_description: Any

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.raw_value(self.data) is not None
