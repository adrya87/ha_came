"""
The CAME Integration Component.

For more details about this platform, please refer to the documentation at
https://github.com/lrzdeveloper/ha-came
"""
import logging
from typing import Any, Dict, Optional

from homeassistant.const import ATTR_ATTRIBUTION, CONF_ENTITIES
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from .pycame.devices import CameDevice

from .const import ATTRIBUTION, DOMAIN, SIGNAL_DELETE_ENTITY, SIGNAL_UPDATE_ENTITY

_LOGGER = logging.getLogger(__name__)


async def cleanup_device_registry(hass: HomeAssistant, device_id):
    """Remove device registry entry if there are no remaining entities."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    if device_id and not er.async_entries_for_device(
        entity_registry, device_id, include_disabled_entities=True
    ):
        device_registry.async_remove_device(device_id)


class CameEntity(Entity):
    """CAME base entity."""

    def __init__(self, device: CameDevice):
        """Init."""
        self._device = device

        self._attr_should_poll = False
        self._attr_unique_id = f"{DOMAIN}_{self._device.unique_id}"
        self._attr_name = self._device.name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{self._device.unique_id}")},
            "name": self._device.name,
            "manufacturer": "CAME",
            "model": self._device.type,
        }

    async def async_added_to_hass(self):
        """Call when entity is added to hass."""
        self.hass.data[DOMAIN][CONF_ENTITIES][self._device.unique_id] = self.entity_id

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_UPDATE_ENTITY, self._update_callback
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DELETE_ENTITY, self._delete_callback
            )
        )

    @property
    def device_state_attributes(self) -> Optional[Dict[str, Any]]:
        """Return device specific state attributes."""
        return {
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @callback
    def _update_callback(self):
        """Call update method."""
        self.async_schedule_update_ha_state(True)

    @callback
    def _delete_callback(self, dev_id):
        """Remove this entity."""
        if dev_id == self._device.unique_id:
            self.hass.async_create_task(self._async_delete())

    async def _async_delete(self):
        """Remove this entity from Home Assistant and registries."""
        entity_registry = er.async_get(self.hass)
        if entity_registry.async_is_registered(self.entity_id):
            entity_entry = entity_registry.async_get(self.entity_id)
            entity_registry.async_remove(self.entity_id)
            await cleanup_device_registry(self.hass, entity_entry.device_id)
        else:
            await self.async_remove(force_remove=True)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._device.available
