# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from unittest.mock import MagicMock, patch

import pytest
from pygame.surface import Surface

from tuxemon.database.loader import load_files
from tuxemon.world.ambient import AmbientRenderer
from tuxemon.world.weather_effects import (
    WEATHER_EFFECTS_FILE,
    WeatherEffectConfig,
    WeatherEffectRenderer,
    load_weather_effects,
)


@pytest.fixture
def effects():
    return load_weather_effects(WEATHER_EFFECTS_FILE)


def test_shipped_effects(effects):
    assert set(effects) == {
        "rain",
        "thunderstorm",
        "snow",
        "foggy",
        "misty",
        "cloudy",
    }
    assert effects["rain"].particles.count == 150
    assert effects["thunderstorm"].particles.count == 250
    assert effects["snow"].particles.count == 100
    assert effects["foggy"].overlay[3] == 90
    assert effects["misty"].overlay[3] == 45
    assert effects["cloudy"].overlay[3] == 30
    assert effects["thunderstorm"].lightning.interval == (8, 20)
    assert effects["thunderstorm"].lightning.duration == 0.15


def test_effects_file_not_loaded_as_weather():
    config = MagicMock(file_extensions=[".yaml", ".yml", ".json"])
    entries = load_files("weather", WEATHER_EFFECTS_FILE.parents[1], config)
    assert "sunny" in entries
    assert all(
        "weather_effects.yaml" not in str(e["paths"]) for e in entries.values()
    )


def test_invalid_effects_file(tmp_path):
    path = tmp_path / "weather_effects.yaml"
    path.write_text("rain:\n  particles:\n    kind: hail\n", encoding="utf-8")
    with patch("tuxemon.world.weather_effects.logger") as log:
        assert load_weather_effects(path) == {}
    assert "Invalid weather effects file" in log.warning.call_args.args[0]


def test_unknown_slug_draws_nothing(effects):
    renderer = WeatherEffectRenderer(effects, seed=1)
    renderer.set_weather("sunny", instant=True)
    surface = Surface((256, 144))
    surface.fill((10, 20, 30))
    renderer.update(0.1)
    renderer.draw(surface)
    assert renderer.layers == []
    assert tuple(surface.get_at((5, 5)))[:3] == (10, 20, 30)


def test_instant_rain_has_all_particles(effects):
    renderer = WeatherEffectRenderer(effects, seed=1)
    renderer.set_weather("rain", instant=True)
    surface = Surface((256, 144))
    renderer.draw(surface)
    layer = renderer.layers[0]
    assert layer.intensity == 1.0
    assert layer.visible_particles == 150


def test_cross_fade_over_two_seconds(effects):
    renderer = WeatherEffectRenderer(effects, seed=1)
    surface = Surface((256, 144))
    renderer.set_weather("rain", instant=True)
    renderer.draw(surface)

    renderer.set_weather("snow")
    renderer.draw(surface)
    rain, snow = renderer.layers
    assert (rain.intensity, snow.intensity) == (1.0, 0.0)

    renderer.update(1.0)
    renderer.draw(surface)
    assert rain.intensity == pytest.approx(0.5)
    assert snow.intensity == pytest.approx(0.5)
    assert rain.visible_particles == 75
    assert snow.visible_particles == 50

    renderer.update(1.0)
    assert [layer.slug for layer in renderer.layers] == ["snow"]
    assert snow.intensity == pytest.approx(1.0)


def test_particles_stay_on_screen(effects):
    renderer = WeatherEffectRenderer(effects, seed=3)
    renderer.set_weather("thunderstorm", instant=True)
    surface = Surface((256, 144))
    renderer.draw(surface)
    for _ in range(600):
        renderer.update(1 / 60)
    layer = renderer.layers[0]
    assert len(layer.particles) == 250
    for p in layer.particles:
        assert -0.1 * 256 - 1 <= p.x <= 1.1 * 256 + 1
        assert p.y <= 144 + 20


def test_lightning_flash(effects):
    renderer = WeatherEffectRenderer(effects, seed=5)
    renderer.set_weather("thunderstorm", instant=True)
    surface = Surface((64, 36))
    renderer.draw(surface)
    layer = renderer.layers[0]
    assert 8 <= layer._next_flash <= 20

    layer._next_flash = 0.01
    renderer.update(0.02)
    assert layer._flash_left == pytest.approx(0.15)
    surface.fill((0, 0, 0))
    renderer.draw(surface)
    assert surface.get_at((1, 1))[0] > 150

    renderer.update(0.2)
    assert layer._flash_left == 0.0


def test_overlay_only_effect():
    effects = {"foggy": WeatherEffectConfig(overlay=(255, 255, 255, 90))}
    renderer = WeatherEffectRenderer(effects)
    renderer.set_weather("foggy", instant=True)
    surface = Surface((8, 8))
    surface.fill((0, 0, 0))
    renderer.draw(surface)
    assert 80 <= surface.get_at((0, 0))[0] <= 100


class _Config:
    time_tint = True
    weather_effects = True


def _ambient(inside, slug="rain"):
    map_manager = MagicMock()
    map_manager.current_map = object()
    map_manager.map_inside = inside
    weather_manager = MagicMock(current_slug=slug)
    time_tint = MagicMock()
    effects = MagicMock(slug=None)
    ambient = AmbientRenderer(
        _Config(),
        map_manager,
        weather_manager,
        MagicMock(),
        time_tint,
        effects,
    )
    return ambient, weather_manager, time_tint, effects


def test_ambient_skips_indoor_maps():
    ambient, _, time_tint, effects = _ambient(inside=True)
    surface = Surface((8, 8))
    ambient.draw_weather(surface)
    ambient.draw_tint(surface)
    effects.draw.assert_not_called()
    time_tint.draw.assert_not_called()


def test_ambient_draws_outdoors_and_follows_weather():
    ambient, weather_manager, time_tint, effects = _ambient(inside=False)
    effects.set_weather.assert_called_with("rain", instant=True)
    effects.slug = "rain"

    weather_manager.current_slug = "snow"
    ambient.update(0.1)
    effects.set_weather.assert_called_with("snow")

    surface = Surface((8, 8))
    ambient.draw_weather(surface)
    ambient.draw_tint(surface)
    effects.draw.assert_called_once_with(surface)
    time_tint.draw.assert_called_once_with(surface)


def test_ambient_respects_settings():
    ambient, _, time_tint, effects = _ambient(inside=False)
    ambient.config.time_tint = False
    ambient.config.weather_effects = False
    surface = Surface((8, 8))
    ambient.draw_weather(surface)
    ambient.draw_tint(surface)
    effects.draw.assert_not_called()
    time_tint.draw.assert_not_called()
