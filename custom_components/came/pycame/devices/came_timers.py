"""Timer support for ETI/Domo."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.helpers.dispatcher import async_dispatcher_send

_LOGGER = logging.getLogger(__name__)

MAX_TIMER_INTERVALS = 4
MIN_DAY = 0
MAX_DAY = 6
MIN_TIME_VALUE = -1
DISABLED_TIME = {"hour": -1, "min": 0, "sec": 0}


class TimerManager:
    """Handle CAME timer API commands."""

    def __init__(self, manager):
        self._manager = manager
        self._timers = []

    @property
    def timers(self) -> list[dict[str, Any]]:
        """Return cached timers."""
        return self._timers

    def get_timers(self) -> list[dict[str, Any]]:
        """Return the timer list from the CAME server."""
        if not self.is_supported:
            self._timers = []
            return self._timers

        response = self._manager.application_request(
            {"cmd_name": "timers_list_req"}, "timers_list_resp"
        )
        timers = response.get("array", response.get("result", []))
        if not isinstance(timers, list):
            _LOGGER.warning("Unexpected CAME timer list payload: %s", response)
            timers = []

        self._timers = timers
        _LOGGER.info("CAME timer list refreshed: %d timers", len(self._timers))
        _LOGGER.debug("CAME timer list payload: %s", self._timers)
        return self._timers

    @property
    def is_supported(self) -> bool:
        """Return true if the ETI/Domo feature list exposes timers."""
        features = getattr(self._manager, "_features", None) or []
        return "timers" in features

    def set_timer_enabled(self, timer_id: int, enabled: bool) -> None:
        """Enable or disable a timer."""
        self._manager.application_request(
            {
                "cmd_name": "timers_enable_req",
                "id": timer_id,
                "value": self._bool_to_api(enabled),
            }
        )

    def set_timer_day_enabled(self, timer_id: int, day: int, enabled: bool) -> None:
        """Enable or disable a weekday for a timer."""
        self._validate_day(day)
        self._manager.application_request(
            {
                "cmd_name": "timers_enable_day_req",
                "id": timer_id,
                "day": day,
                "value": self._bool_to_api(enabled),
            }
        )

    def set_timer_timetable(
        self, timer_id: int, timetable: list[dict[str, Any]]
    ) -> None:
        """Set the complete timetable for a timer."""
        timer = self._get_cached_timer(timer_id)
        self._manager.application_request(
            {
                "cmd_name": "timers_set_req",
                "id": timer_id,
                "timetable": self._normalize_timetable(
                    timetable,
                    self._timer_has_stop(timer),
                ),
            }
        )

    def set_timer_interval_value(
        self, timer_id: int, index: int, value: str, time_value: Any
    ) -> None:
        """Set a single interval value using the current timetable API."""
        self._validate_index(index)
        if value not in ("start", "stop"):
            raise ValueError("Timer interval value must be 'start' or 'stop'.")

        timer = self._get_cached_timer(timer_id)
        has_stop = self._timer_has_stop(timer)
        if value == "stop" and not has_stop:
            raise ValueError("This CAME timer does not support stop time.")

        time_payload = self._normalize_time(time_value)
        timetable = self._ordered_timetable(timer, has_stop)
        interval = timetable[index]
        interval[value] = time_payload

        if value == "start" and has_stop and not self._is_time_enabled(
            interval.get("stop")
        ):
            interval["stop"] = dict(time_payload)
        if value == "stop" and not self._is_time_enabled(interval.get("start")):
            interval["start"] = dict(time_payload)

        self._send_timetable(timer_id, timetable, has_stop)

    def set_timer_interval_active(
        self, timer_id: int, index: int, active: bool
    ) -> None:
        """Enable or disable a single timer interval."""
        self._validate_index(index)

        timer = self._get_cached_timer(timer_id)
        has_stop = self._timer_has_stop(timer)
        timetable = self._ordered_timetable(timer, has_stop)
        interval = timetable[index]

        if active:
            if not self._is_time_enabled(interval.get("start")):
                interval["start"] = {"hour": 0, "min": 0, "sec": 0}
            if has_stop and not self._is_time_enabled(interval.get("stop")):
                interval["stop"] = dict(interval["start"])
        else:
            interval["start"] = dict(DISABLED_TIME)
            if has_stop:
                interval["stop"] = dict(DISABLED_TIME)

        self._send_timetable(timer_id, timetable, has_stop)

    def handle_update(self, hass, device_info: dict[str, Any]) -> None:
        """Handle timer status notifications."""
        if device_info.get("cmd_name") != "timer_info_ind":
            return

        timer_id = device_info.get("id")
        self._timers = [
            timer for timer in self._timers if timer.get("id") != timer_id
        ]
        self._timers.append(device_info)

        if hass is not None:
            hass.add_job(
                async_dispatcher_send,
                hass,
                "came_timer_update",
                timer_id,
                device_info,
            )
            hass.add_job(async_dispatcher_send, hass, "came_timers_refreshed")

    @staticmethod
    def _bool_to_api(value: bool) -> int:
        if isinstance(value, str):
            return 1 if value.lower() in ("1", "true", "on", "yes") else 0
        return 1 if value else 0

    @staticmethod
    def _validate_day(day: int) -> None:
        if day < MIN_DAY or day > MAX_DAY:
            raise ValueError("Timer day must be between 0 and 6, where 0 is Monday.")

    @staticmethod
    def _validate_index(index: int) -> None:
        if index < 0 or index >= MAX_TIMER_INTERVALS:
            raise ValueError("Timer interval index must be between 0 and 3.")

    def _get_cached_timer(self, timer_id: int) -> dict[str, Any]:
        for timer in self._timers:
            if timer.get("id") == timer_id:
                return timer
        timers = self.get_timers()
        for timer in timers:
            if timer.get("id") == timer_id:
                return timer
        raise ValueError(f"Timer {timer_id} not found.")

    def _normalize_timetable(
        self, timetable: list[dict[str, Any]], has_stop: bool
    ) -> list[dict[str, Any]]:
        if not isinstance(timetable, list):
            raise ValueError("Timer timetable must be a list.")
        if len(timetable) > MAX_TIMER_INTERVALS:
            raise ValueError("A timer can have at most 4 intervals.")

        ordered = [self._disabled_interval(has_stop) for _ in range(MAX_TIMER_INTERVALS)]
        max_index = -1
        for position, interval in enumerate(timetable):
            if not isinstance(interval, dict):
                raise ValueError("Timer interval must be a dictionary.")
            index = int(interval.get("index", position))
            self._validate_index(index)
            ordered[index] = self._normalize_interval(interval, has_stop)
            max_index = max(max_index, index)

        if max_index < 0:
            return []
        return ordered[: max_index + 1]

    def _normalize_interval(
        self, interval: dict[str, Any], has_stop: bool
    ) -> dict[str, Any]:
        if not isinstance(interval, dict):
            raise ValueError("Timer interval must be a dictionary.")
        if "start" not in interval:
            raise ValueError("Timer interval requires a start time.")

        normalized = {"start": self._normalize_time(interval["start"])}
        if has_stop and "stop" in interval and interval["stop"] is not None:
            normalized["stop"] = self._normalize_time(interval["stop"])
        elif has_stop:
            normalized["stop"] = dict(DISABLED_TIME)

        return normalized

    def _send_timetable(
        self, timer_id: int, timetable: list[dict[str, Any]], has_stop: bool
    ) -> None:
        self._manager.application_request(
            {
                "cmd_name": "timers_set_req",
                "id": timer_id,
                "timetable": self._normalize_timetable(timetable, has_stop),
            }
        )

    def _ordered_timetable(
        self, timer: dict[str, Any], has_stop: bool
    ) -> list[dict[str, Any]]:
        ordered = [self._disabled_interval(has_stop) for _ in range(MAX_TIMER_INTERVALS)]
        for position, interval in enumerate(timer.get("timetable", []) or []):
            if not isinstance(interval, dict):
                continue
            index = int(interval.get("index", position))
            if index < 0 or index >= MAX_TIMER_INTERVALS:
                continue
            ordered[index] = self._normalize_interval(interval, has_stop)
        return ordered

    @staticmethod
    def _disabled_interval(has_stop: bool) -> dict[str, Any]:
        interval = {"start": dict(DISABLED_TIME)}
        if has_stop:
            interval["stop"] = dict(DISABLED_TIME)
        return interval

    @staticmethod
    def _timer_has_stop(timer: dict[str, Any]) -> bool:
        if timer.get("bars") == 1:
            return False
        for interval in timer.get("timetable", []) or []:
            if isinstance(interval, dict) and "stop" in interval:
                return True
        return timer.get("bars") != 1

    @staticmethod
    def _is_time_enabled(value: Any) -> bool:
        return isinstance(value, dict) and value.get("hour", -1) >= 0

    @staticmethod
    def _normalize_time(value: Any) -> dict[str, int]:
        if isinstance(value, str):
            parts = value.split(":")
            if len(parts) not in (2, 3):
                raise ValueError("Timer time must use HH:MM or HH:MM:SS format.")
            hour, minute = int(parts[0]), int(parts[1])
            second = int(parts[2]) if len(parts) == 3 else 0
        elif isinstance(value, dict):
            hour = int(value.get("hour", 0))
            minute = int(value.get("min", value.get("minute", 0)))
            second = int(value.get("sec", value.get("second", 0)))
        else:
            raise ValueError("Timer time must be a string or a dictionary.")

        if hour < MIN_TIME_VALUE or hour > 23:
            raise ValueError("Timer hour must be between -1 and 23.")
        if minute < 0 or minute > 59:
            raise ValueError("Timer minute must be between 0 and 59.")
        if second < 0 or second > 59:
            raise ValueError("Timer second must be between 0 and 59.")

        return {"hour": hour, "min": minute, "sec": second}
