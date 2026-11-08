# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import ClassVar

from tuxemon.database.runtime import db
from tuxemon.event.eventcondition import EventCondition
from tuxemon.session import Session

logger = logging.getLogger(__name__)


@dataclass
class WeatherIsCondition(EventCondition):
    """
    Checks the current world weather managed by the WorldWeatherManager.

    Script usage:
        .. code-block::

            is weather_is <slug>[,<slug>...]

    Script parameters:
        slug:
            One or more weather slugs from the weather database
            (e.g. "rain", "snow", "thunderstorm"). The condition is true
            when the current weather matches any of them.

    Example:
        .. code-block::

            is weather_is rain
            is weather_is rain,thunderstorm
            not weather_is sunny
    """

    name: ClassVar[str] = "weather_is"
    slugs: list[str] = field(default_factory=list, init=False)

    def __init__(self, *args: str):
        self.slugs = []
        for arg in args:
            self.slugs.extend(s.strip() for s in arg.split(",") if s.strip())
        self.__post_init__()

    def test(self, session: Session) -> bool:
        manager = getattr(session.client, "weather_manager", None)
        if manager is None or manager.current_slug is None:
            return False

        if not self.slugs:
            logger.warning("weather_is: no weather slug given")
            return False

        known = db.database.get("weather", {})
        unknown = [s for s in self.slugs if s not in known]
        if unknown:
            logger.warning(
                f"weather_is: unknown weather slug(s) {', '.join(unknown)}"
            )
            return False

        return manager.current_slug in self.slugs
