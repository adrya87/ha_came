"""Support for the CAME relays."""
import logging
from typing import List


from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.switch import (
    SwitchEntity,
)


from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from .pycame.came_manager import CameManager
from .pycame.devices import CameDevice
from .pycame.devices.came_relay import GENERIC_RELAY_STATE_ON

from .const import CONF_MANAGER, CONF_PENDING, DOMAIN, SIGNAL_DISCOVERY_NEW
from .entity import CameEntity

_LOGGER = logging.getLogger(__name__)
SIGNAL_TIMERS_REFRESHED = "came_timers_refreshed"
DAYS = (
    "Lunedi",
    "Martedi",
    "Mercoledi",
    "Giovedi",
    "Venerdi",
    "Sabato",
    "Domenica",
)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
):
    """Set up CAME relay devices dynamically through discovery."""

    async def async_discover_sensor(dev_ids):
        """Discover and add a discovered CAME relay devices."""
        if not dev_ids:
            return

        entities = await hass.async_add_executor_job(_setup_entities, hass, dev_ids)
        async_add_entities(entities)

    async def async_discover_timer_switches():
        """Discover and add CAME timer switches."""
        entities = await hass.async_add_executor_job(_setup_timer_entities, hass)
        if entities:
            async_add_entities(entities)

    config_entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_DISCOVERY_NEW.format(SWITCH_DOMAIN), async_discover_sensor
        )
    )
    config_entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_TIMERS_REFRESHED, async_discover_timer_switches
        )
    )

    devices_ids = hass.data[DOMAIN][CONF_PENDING].pop(SWITCH_DOMAIN, [])
    await async_discover_sensor(devices_ids)
    await async_discover_timer_switches()


def _setup_entities(hass, dev_ids: List[str]):
    """Set up CAME switch device."""
    manager = hass.data[DOMAIN][CONF_MANAGER]  # type: CameManager
    entities = []
    for dev_id in dev_ids:
        device = manager.get_device_by_id(dev_id)
        if device is None:
            continue
        entities.append(CameSwitchEntity(device))
    return entities


def _setup_timer_entities(hass):
    """Set up CAME timer switch entities."""
    manager = hass.data[DOMAIN][CONF_MANAGER]  # type: CameManager
    timer_manager = manager.timer_manager
    entities = []
    known_switches = hass.data[DOMAIN].setdefault("came_timer_switch_entities", set())

    try:
        timers = timer_manager.get_timers()
    except Exception as exc:  # pylint: disable=broad-except
        _LOGGER.warning("Unable to retrieve CAME timers for switches: %s", exc)
        return entities

    for timer in timers:
        timer_id = timer.get("id")
        if timer_id is None:
            continue

        enabled_key = (timer_id, "enabled")
        if enabled_key not in known_switches:
            known_switches.add(enabled_key)
            entities.append(CameTimerEnabledSwitchEntity(timer_manager, timer))

        for day in range(7):
            day_key = (timer_id, "day", day)
            if day_key in known_switches:
                continue
            known_switches.add(day_key)
            entities.append(CameTimerDaySwitchEntity(timer_manager, timer, day))

        for interval_index in range(4):
            interval_key = (timer_id, "interval", interval_index, "active")
            if interval_key in known_switches:
                continue
            known_switches.add(interval_key)
            entities.append(
                CameTimerIntervalSwitchEntity(timer_manager, timer, interval_index)
            )

    return entities


class CameSwitchEntity(CameEntity, SwitchEntity):
    """CAME relay device entity."""

    def __init__(self, device: CameDevice):
        """Init CAME switch device entity."""
        super().__init__(device)


    @property
    def is_on(self):
        """Return true if relay is on."""
        return self._device.state == GENERIC_RELAY_STATE_ON

    def turn_on(self, **kwargs):
        """Turn on or control the relay."""
        _LOGGER.debug("Turn on relay %s", self.entity_id)
        self._device.turn_on()


    def turn_off(self, **kwargs):
        """Instruct the relay to turn off."""
        _LOGGER.debug("Turn off relay %s", self.entity_id)
        self._device.turn_off()


class CameTimerSwitchBase(SwitchEntity):
    """Base CAME timer switch entity."""

    _attr_should_poll = False

    def __init__(self, timer_manager, timer: dict):
        self._timer_manager = timer_manager
        self._timer = timer
        self._timer_id = timer.get("id")
        self._timer_name = timer.get("name") or f"Timer {self._timer_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"timer_{self._timer_id}")},
            "name": str(self._timer_name),
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

    def _refresh_timer(self):
        for timer in self._timer_manager.timers:
            if timer.get("id") == self._timer_id:
                self._timer = timer
                self.async_write_ha_state()
                return

    @callback
    def _timers_refreshed_callback(self):
        self._refresh_timer()

    async def _async_refresh_timers(self):
        await self.hass.async_add_executor_job(self._timer_manager.get_timers)
        async_dispatcher_send(self.hass, SIGNAL_TIMERS_REFRESHED)

    @staticmethod
    def _is_enabled(value) -> bool:
        if isinstance(value, str):
            return value.lower() in ("1", "true", "on", "yes")
        return value == 1 or value is True


class CameTimerEnabledSwitchEntity(CameTimerSwitchBase):
    """CAME timer enabled switch."""

    def __init__(self, timer_manager, timer: dict):
        super().__init__(timer_manager, timer)
        self._attr_unique_id = f"{DOMAIN}_timer_{self._timer_id}_enabled"
        self._attr_name = f"{self._timer_name} Abilitato"

    @property
    def is_on(self):
        """Return true if timer is enabled."""
        return self._is_enabled(self._timer.get("enabled"))

    def turn_on(self, **kwargs):
        """Enable the timer."""
        self._timer_manager.set_timer_enabled(self._timer_id, True)
        self._timer_manager.get_timers()
        self._refresh_timer()

    async def async_turn_on(self, **kwargs):
        """Enable the timer."""
        await self.hass.async_add_executor_job(
            self._timer_manager.set_timer_enabled, self._timer_id, True
        )
        await self._async_refresh_timers()

    def turn_off(self, **kwargs):
        """Disable the timer."""
        self._timer_manager.set_timer_enabled(self._timer_id, False)
        self._timer_manager.get_timers()
        self._refresh_timer()

    async def async_turn_off(self, **kwargs):
        """Disable the timer."""
        await self.hass.async_add_executor_job(
            self._timer_manager.set_timer_enabled, self._timer_id, False
        )
        await self._async_refresh_timers()


class CameTimerDaySwitchEntity(CameTimerSwitchBase):
    """CAME timer day switch."""

    def __init__(self, timer_manager, timer: dict, day: int):
        super().__init__(timer_manager, timer)
        self._day = day
        self._attr_unique_id = f"{DOMAIN}_timer_{self._timer_id}_day_{day}"
        self._attr_name = f"{self._timer_name} {DAYS[day]}"

    @property
    def is_on(self):
        """Return true if timer day is enabled."""
        days_mask = int(self._timer.get("days", 0) or 0)
        return bool(days_mask & (1 << self._day))

    def turn_on(self, **kwargs):
        """Enable the timer day."""
        self._timer_manager.set_timer_day_enabled(self._timer_id, self._day, True)
        self._timer_manager.get_timers()
        self._refresh_timer()

    async def async_turn_on(self, **kwargs):
        """Enable the timer day."""
        await self.hass.async_add_executor_job(
            self._timer_manager.set_timer_day_enabled,
            self._timer_id,
            self._day,
            True,
        )
        await self._async_refresh_timers()

    def turn_off(self, **kwargs):
        """Disable the timer day."""
        self._timer_manager.set_timer_day_enabled(self._timer_id, self._day, False)
        self._timer_manager.get_timers()
        self._refresh_timer()

    async def async_turn_off(self, **kwargs):
        """Disable the timer day."""
        await self.hass.async_add_executor_job(
            self._timer_manager.set_timer_day_enabled,
            self._timer_id,
            self._day,
            False,
        )
        await self._async_refresh_timers()


class CameTimerIntervalSwitchEntity(CameTimerSwitchBase):
    """CAME timer interval active switch."""

    def __init__(self, timer_manager, timer: dict, interval_index: int):
        super().__init__(timer_manager, timer)
        self._interval_index = interval_index
        self._attr_unique_id = (
            f"{DOMAIN}_timer_{self._timer_id}_interval_"
            f"{interval_index + 1}_active"
        )
        self._attr_name = (
            f"{self._timer_name} Intervallo {interval_index + 1} Attivo"
        )

    @property
    def is_on(self):
        """Return true if timer interval is enabled."""
        return self._is_interval_enabled(self._interval())

    def turn_on(self, **kwargs):
        """Enable the timer interval."""
        self._timer_manager.set_timer_interval_active(
            self._timer_id, self._interval_index, True
        )
        self._timer_manager.get_timers()
        self._refresh_timer()

    async def async_turn_on(self, **kwargs):
        """Enable the timer interval."""
        await self.hass.async_add_executor_job(
            self._timer_manager.set_timer_interval_active,
            self._timer_id,
            self._interval_index,
            True,
        )
        await self._async_refresh_timers()

    def turn_off(self, **kwargs):
        """Disable the timer interval."""
        self._timer_manager.set_timer_interval_active(
            self._timer_id, self._interval_index, False
        )
        self._timer_manager.get_timers()
        self._refresh_timer()

    async def async_turn_off(self, **kwargs):
        """Disable the timer interval."""
        await self.hass.async_add_executor_job(
            self._timer_manager.set_timer_interval_active,
            self._timer_id,
            self._interval_index,
            False,
        )
        await self._async_refresh_timers()

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

    @staticmethod
    def _is_interval_enabled(interval: dict) -> bool:
        start = interval.get("start")
        if isinstance(start, dict):
            return start.get("hour", -1) >= 0
        return False
