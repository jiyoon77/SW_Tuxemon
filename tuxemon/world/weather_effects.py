# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
"""Screen-space weather effects (rain, snow, fog layers, lightning)."""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pygame import SRCALPHA
from pygame.draw import circle, line
from pygame.surface import Surface

from tuxemon.constants import paths
from tuxemon.database.yaml_utils import load_yaml

logger = logging.getLogger(__name__)

WEATHER_EFFECTS_FILE: Final[Path] = (
    paths.mods_folder / "tuxemon" / "db" / "weather" / "weather_effects.yaml"
)
WEATHER_FADE_SECONDS: Final[float] = 2.0
# Speeds, lengths and sizes in the config are given for the native
# 144 px high screen and scaled to the actual screen height.
NATIVE_HEIGHT: Final[int] = 144

RGBA = tuple[int, int, int, int]


class ParticleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["rain", "snow"]
    count: int = Field(..., ge=0)
    color: RGBA
    speed: tuple[float, float] = Field(
        ..., description="Min/max fall speed in native px per second."
    )
    drift: float = Field(
        0.0, description="Horizontal speed in native px per second."
    )
    length: float = Field(6.0, ge=0, description="Rain streak length.")
    width: int = Field(1, ge=1, description="Rain streak width.")
    radius: tuple[float, float] = Field(
        (1.0, 1.5), description="Min/max snow flake radius."
    )
    sway: float = Field(0.0, ge=0, description="Snow sway amplitude.")
    sway_speed: float = Field(1.0, ge=0, description="Snow sway rate.")


class LightningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval: tuple[float, float] = Field(
        ..., description="Min/max seconds between flashes."
    )
    duration: float = Field(0.15, gt=0)
    color: RGBA = (255, 255, 255, 180)


class WeatherEffectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overlay: RGBA | None = None
    particles: ParticleConfig | None = None
    lightning: LightningConfig | None = None


def load_weather_effects(
    path: Path = WEATHER_EFFECTS_FILE,
) -> dict[str, WeatherEffectConfig]:
    """
    Reads the per-weather effect settings. Returns an empty mapping (no
    effects) when the file is missing or invalid.
    """
    if not path.exists():
        logger.warning(f"Weather effects file '{path}' not found.")
        return {}
    try:
        data = load_yaml(path)
        if not isinstance(data, dict):
            raise ValueError("top level must be a mapping")
        return {
            str(slug): WeatherEffectConfig.model_validate(value or {})
            for slug, value in data.items()
        }
    except (ValueError, ValidationError) as exc:
        logger.warning(f"Invalid weather effects file '{path}': {exc}")
        return {}


@dataclass
class _Particle:
    x: float
    y: float
    speed: float
    size: float
    phase: float


class _EffectLayer:
    """One weather's effect plus its fade in/out state."""

    def __init__(
        self,
        slug: str,
        config: WeatherEffectConfig,
        rng: random.Random,
        intensity: float,
    ) -> None:
        self.slug = slug
        self.config = config
        self.rng = rng
        self.intensity = intensity
        self.target = 1.0
        self.particles: list[_Particle] = []
        self._size: tuple[int, int] | None = None
        self._time = 0.0
        self._flash_left = 0.0
        self._next_flash = self._roll_flash_delay()

    @property
    def finished(self) -> bool:
        return self.target == 0.0 and self.intensity <= 0.0

    def _roll_flash_delay(self) -> float:
        if self.config.lightning is None:
            return math.inf
        low, high = self.config.lightning.interval
        return self.rng.uniform(low, high)

    def _spawn(self, width: int, height: int, scale: float) -> _Particle:
        cfg = self.config.particles
        assert cfg is not None
        return _Particle(
            x=self.rng.uniform(-0.1 * width, 1.1 * width),
            y=self.rng.uniform(0, height),
            speed=self.rng.uniform(*cfg.speed) * scale,
            size=self.rng.uniform(*cfg.radius) * scale,
            phase=self.rng.uniform(0, math.tau),
        )

    def resize(self, size: tuple[int, int]) -> None:
        if size == self._size or self.config.particles is None:
            self._size = size
            return
        self._size = size
        width, height = size
        scale = height / NATIVE_HEIGHT
        self.particles = [
            self._spawn(width, height, scale)
            for _ in range(self.config.particles.count)
        ]

    def update(self, dt: float, fade_step: float) -> None:
        if self.intensity < self.target:
            self.intensity = min(self.target, self.intensity + fade_step)
        elif self.intensity > self.target:
            self.intensity = max(self.target, self.intensity - fade_step)

        self._time += dt
        self._update_lightning(dt)
        self._update_particles(dt)

    def _update_lightning(self, dt: float) -> None:
        if self.config.lightning is None:
            return
        if self._flash_left > 0:
            self._flash_left = max(0.0, self._flash_left - dt)
        self._next_flash -= dt
        if self._next_flash <= 0:
            self._flash_left = self.config.lightning.duration
            self._next_flash = self._roll_flash_delay()

    def _update_particles(self, dt: float) -> None:
        cfg = self.config.particles
        if cfg is None or self._size is None:
            return
        width, height = self._size
        scale = height / NATIVE_HEIGHT
        drift = cfg.drift * scale
        margin = cfg.length * scale + 2

        for p in self.particles:
            p.y += p.speed * dt
            if cfg.kind == "rain":
                p.x += drift * dt
            if p.y > height + margin:
                p.y = -self.rng.uniform(0, margin)
                p.x = self.rng.uniform(-0.1 * width, 1.1 * width)
            elif p.x < -0.1 * width:
                p.x += 1.2 * width
            elif p.x > 1.1 * width:
                p.x -= 1.2 * width

    @property
    def visible_particles(self) -> int:
        cfg = self.config.particles
        if cfg is None:
            return 0
        return int(len(self.particles) * self.intensity)

    def draw(self, layer: Surface) -> None:
        if self.intensity <= 0:
            return
        if self.config.overlay is not None:
            r, g, b, a = self.config.overlay
            layer.fill((r, g, b, int(a * self.intensity)))
        self._draw_particles(layer)
        if self.config.lightning is not None and self._flash_left > 0:
            r, g, b, a = self.config.lightning.color
            layer.fill((r, g, b, int(a * self.intensity)))

    def _draw_particles(self, layer: Surface) -> None:
        cfg = self.config.particles
        if cfg is None or self._size is None:
            return
        scale = self._size[1] / NATIVE_HEIGHT
        r, g, b, a = cfg.color
        color = (r, g, b, int(a * self.intensity))

        if cfg.kind == "rain":
            speed_mid = (cfg.speed[0] + cfg.speed[1]) / 2 or 1.0
            length = cfg.length * scale
            dx = cfg.drift / speed_mid * length
            width = max(1, round(cfg.width * scale / 2))
            for p in self.particles[: self.visible_particles]:
                line(layer, color, (p.x, p.y), (p.x + dx, p.y + length), width)
        else:
            sway = cfg.sway * scale
            for p in self.particles[: self.visible_particles]:
                x = (
                    p.x
                    + math.sin(p.phase + self._time * cfg.sway_speed) * sway
                )
                circle(
                    layer, color, (round(x), round(p.y)), max(1, round(p.size))
                )


class WeatherEffectRenderer:
    """
    Draws the effect of the current weather in screen coordinates.

    ``set_weather`` cross-fades from the previous effect over
    ``fade_duration`` seconds; with ``instant=True`` the new effect is shown
    at full strength right away. Slugs without a configured effect draw
    nothing.
    """

    def __init__(
        self,
        effects: dict[str, WeatherEffectConfig] | None = None,
        fade_duration: float = WEATHER_FADE_SECONDS,
        seed: int | None = None,
    ) -> None:
        self.effects = (
            effects if effects is not None else load_weather_effects()
        )
        self.fade_duration = fade_duration
        self.rng = random.Random(seed)
        self.slug: str | None = None
        self.layers: list[_EffectLayer] = []
        self._surface: Surface | None = None

    def set_weather(self, slug: str | None, instant: bool = False) -> None:
        if slug == self.slug and not instant:
            return
        self.slug = slug

        if instant:
            self.layers.clear()
        else:
            for layer in self.layers:
                layer.target = 0.0

        config = self.effects.get(slug) if slug else None
        if slug is None or config is None:
            return

        for layer in self.layers:
            if layer.slug == slug:
                layer.target = 1.0
                return

        start = 1.0 if instant or self.fade_duration <= 0 else 0.0
        self.layers.append(_EffectLayer(slug, config, self.rng, start))

    def update(self, dt: float) -> None:
        if self.fade_duration > 0:
            fade_step = dt / self.fade_duration
        else:
            fade_step = 1.0
        for layer in self.layers:
            layer.update(dt, fade_step)
        self.layers = [layer for layer in self.layers if not layer.finished]

    def draw(self, surface: Surface) -> None:
        if not self.layers:
            return
        size = surface.get_size()
        if self._surface is None or self._surface.get_size() != size:
            self._surface = Surface(size, SRCALPHA)

        for layer in self.layers:
            layer.resize(size)
            self._surface.fill((0, 0, 0, 0))
            layer.draw(self._surface)
            surface.blit(self._surface, (0, 0))
