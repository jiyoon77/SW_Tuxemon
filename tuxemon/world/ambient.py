# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
"""Weather effects and stage-of-day tint for outdoor maps."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pygame.surface import Surface

from tuxemon.world.time_tint import TimeTintRenderer
from tuxemon.world.weather_effects import WeatherEffectRenderer

if TYPE_CHECKING:
    from tuxemon.config import TuxemonConfig
    from tuxemon.map.manager import MapManager
    from tuxemon.time_handler import TimeHandler
    from tuxemon.world.weather import WorldWeatherManager


class AmbientRenderer:
    """
    Draws the current weather effect and the time-of-day tint over the map.
    Nothing is drawn on indoor maps. Each part can be switched off in the
    graphics settings.
    """

    def __init__(
        self,
        config: TuxemonConfig,
        map_manager: MapManager,
        weather_manager: WorldWeatherManager,
        time_handler: TimeHandler,
        time_tint: TimeTintRenderer | None = None,
        weather_effects: WeatherEffectRenderer | None = None,
    ) -> None:
        self.config = config
        self.map_manager = map_manager
        self.weather_manager = weather_manager
        self.time_tint = time_tint or TimeTintRenderer(time_handler)
        self.weather_effects = weather_effects or WeatherEffectRenderer()
        self.snap()

    @property
    def outdoors(self) -> bool:
        return (
            self.map_manager.current_map is not None
            and not self.map_manager.map_inside
        )

    def snap(self) -> None:
        """Show the current tint and weather without any transition."""
        self.time_tint.snap()
        self.weather_effects.set_weather(
            self.weather_manager.current_slug, instant=True
        )

    def update(self, dt: float) -> None:
        self.time_tint.update(dt)
        slug = self.weather_manager.current_slug
        if not self.config.weather_effects:
            if slug != self.weather_effects.slug:
                self.weather_effects.set_weather(slug, instant=True)
            return
        if slug != self.weather_effects.slug:
            self.weather_effects.set_weather(slug)
        self.weather_effects.update(dt)

    def draw_weather(self, surface: Surface) -> None:
        if self.config.weather_effects and self.outdoors:
            self.weather_effects.draw(surface)

    def draw_tint(self, surface: Surface) -> None:
        if self.config.time_tint and self.outdoors:
            self.time_tint.draw(surface)
