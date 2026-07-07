"""Support for editable CAME timer intervals."""

from __future__ import annotations

import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)

from .const import CONF_MANAGER, DOMAIN
from .pycame.came_manager import CameManager

_LOGGER = logging.getLogger(__name__)
SIGNAL_TIMERS_REFRESHED = "came_timers_refreshed"


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
):
    """Set up editable CAME timer interval time entities."""

    async def async_discover_timer_times():
        """Discover and add CAME timer time entities."""
        entities = await hass.async_add_executor_job(_setup_timer_entities, hass)
        if entities:
            async_add_entities(entities)

    config_entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_TIMERS_REFRESHED, async_discover_timer_times
        )
    )

    await async_discover_timer_times()


def _setup_timer_entities(hass):
    """Set up editable CAME timer time entities."""
    manager = hass.data[DOMAIN][CONF_MANAGER]  # type: CameManager
    timer_manager = manager.timer_manager
    entities = []
    known_times = hass.data[DOMAIN].setdefault("came_timer_time_entities", set())

    try:
        timers = timer_manager.get_timers()
    except Exception as exc:  # pylint: disable=broad-except
        _LOGGER.warning("Unable to retrieve CAME timers for time entities: %s", exc)
        return entities

    for timer_item in timers:
        timer_id = timer_item.get("id")
        if timer_id is None:
            continue

        values = ("start",) if _is_start_only_timer(timer_item) else ("start", "stop")
        for interval_index in range(4):
            for value_name in values:
                key = (timer_id, interval_index, value_name)
                if key in known_times:
                    continue
                known_times.add(key)
                entities.append(
                    CameTimerTimeEntity(
                        timer_manager,
                        timer_item,
                        interval_index,
                        value_name,
                    )
                )

    return entities


def _is_start_only_timer(timer_item: dict) -> bool:
    """Return true if the CAME timer supports only a start time."""
    if timer_item.get("bars") == 1:
        return True
    for interval in timer_item.get("timetable", []) or []:
        if isinstance(interval, dict) and "stop" in interval:
            return False
    return timer_item.get("bars") == 1


class CameTimerTimeEntity(TimeEntity):
    """Editable CAME timer interval time entity."""

    _attr_should_poll = False

    def __init__(
        self,
        timer_manager,
        timer_item: dict,
        interval_index: int,
        value_name: str,
    ):
        """Init editable CAME timer interval time entity."""
        self._timer_manager = timer_manager
        self._timer = timer_item
        self._timer_id = timer_item.get("id")
        self._interval_index = interval_index
        self._value_name = value_name
        timer_name = timer_item.get("name") or f"Timer {self._timer_id}"
        label = "Inizio" if value_name == "start" else "Fine"

        self._attr_unique_id = (
            f"{DOMAIN}_timer_{self._timer_id}_interval_"
            f"{interval_index + 1}_{value_name}"
        )
        self._attr_name = f"{timer_name} Intervallo {interval_index + 1} {label}"
        self._attr_icon = "mdi:clock-edit-outline"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"timer_{self._timer_id}")},
            "name": str(timer_name),
            "manufacturer": "CAME",
            "model": "Timer scheduler",
        }

    async def async_added_to_hass(self):
        """Subscribe to timer refresh events."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_TIMERS_REFRESHED, self._timers_refreshed_callback
            )
        )

    @property
    def native_value(self) -> time | None:
        """Return the configured interval time."""
        return self._time_value()

    def set_value(self, value: time) -> None:
        """Set the interval time."""
        self._timer_manager.set_timer_interval_value(
            self._timer_id,
            self._interval_index,
            self._value_name,
            value.strftime("%H:%M:%S"),
        )
        self._timer_manager.get_timers()
        self._refresh_timer()

    async def async_set_value(self, value: time) -> None:
        """Set the interval time."""
        await self.hass.async_add_executor_job(
            self._timer_manager.set_timer_interval_value,
            self._timer_id,
            self._interval_index,
            self._value_name,
            value.strftime("%H:%M:%S"),
        )
        await self.hass.async_add_executor_job(self._timer_manager.get_timers)
        async_dispatcher_send(self.hass, SIGNAL_TIMERS_REFRESHED)

    @callback
    def _timers_refreshed_callback(self):
        """Handle a complete timer list refresh."""
        self._refresh_timer()

    def _refresh_timer(self):
        for timer_item in self._timer_manager.timers:
            if timer_item.get("id") == self._timer_id:
                self._timer = timer_item
                self.async_write_ha_state()
                return

    def _time_value(self) -> time | None:
        interval = self._interval()
        value = interval.get(self._value_name)
        if not isinstance(value, dict):
            return None

        hour = value.get("hour")
        minute = value.get("min", 0)
        second = value.get("sec", 0)
        if hour is None or hour < 0:
            return None

        return time(hour=hour, minute=minute or 0, second=second or 0)

    def _interval(self) -> dict:
        timetable = self._timer.get("timetable", [])
        for interval in timetable or []:
            if isinstance(interval, dict) and interval.get("index") == self._interval_index:
                return interval

        if self._interval_index < len(timetable):
            interval = timetable[self._interval_index]
            if isinstance(interval, dict):
                return interval

        return {}
