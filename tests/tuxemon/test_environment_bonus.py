# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tuxemon.combat import environment_bonus as eb
from tuxemon.constants import paths
from tuxemon.core.effects.damage import DamageEffect
from tuxemon.core.effects.multiattack import MultiAttackEffect
from tuxemon.database.yaml_utils import load_yaml
from tuxemon.db import Modifier, WeatherModel
from tuxemon.time_handler import TimeHandler

DB = paths.mods_folder / "tuxemon" / "db"


def mod(element, multiplier):
    return Modifier(attribute="type", values=[element], multiplier=multiplier)


RAIN = [mod("water", 1.2), mod("fire", 0.8)]
HOT = [mod("fire", 1.2), mod("frost", 0.8)]
SEASONS = {
    "spring": [mod("wood", 1.1)],
    "summer": [mod("fire", 1.1)],
    "autumn": [mod("earth", 1.1)],
    "winter": [mod("frost", 1.1)],
}


def monster(*elements):
    m = MagicMock()
    m.types.current = [SimpleNamespace(slug=e) for e in elements]
    m.hp_ratio = 1.0
    return m


def session(weather_mods=None, month=6, hemisphere="northern", manager=True):
    time = TimeHandler(hemisphere)
    time.get_current_time = lambda: datetime(2026, month, 15, 12)
    if not manager:
        client = SimpleNamespace()
    elif weather_mods is None:
        client = SimpleNamespace(
            weather_manager=SimpleNamespace(current_weather=None)
        )
    else:
        weather = SimpleNamespace(modifiers=weather_mods)
        client = SimpleNamespace(
            weather_manager=SimpleNamespace(current_weather=weather)
        )
    return SimpleNamespace(client=client, time=time)


# --- multiplier ----------------------------------------------------------


@pytest.mark.parametrize(
    "elements,expected",
    [
        pytest.param(("water",), 1.2, id="water_boosted"),
        pytest.param(("fire",), 0.8, id="fire_weakened"),
        pytest.param(("earth",), 1.0, id="unrelated"),
        pytest.param(("water", "fire"), 0.96, id="dual_type_cumulative"),
    ],
)
def test_weather_only(elements, expected):
    s = session(RAIN)
    mult = eb.get_environment_multiplier(s, monster(*elements), {})
    assert mult == pytest.approx(expected)


@pytest.mark.parametrize(
    "month,hemisphere,boosted",
    [
        pytest.param(4, "northern", "wood", id="north_spring"),
        pytest.param(7, "northern", "fire", id="north_summer"),
        pytest.param(10, "northern", "earth", id="north_autumn"),
        pytest.param(1, "northern", "frost", id="north_winter"),
        pytest.param(7, "southern", "frost", id="south_july_winter"),
        pytest.param(1, "southern", "fire", id="south_january_summer"),
    ],
)
def test_season_only(month, hemisphere, boosted):
    s = session(None, month=month, hemisphere=hemisphere)
    assert eb.get_environment_multiplier(
        s, monster(boosted), SEASONS
    ) == pytest.approx(1.1)
    assert eb.get_environment_multiplier(
        s, monster("normal"), SEASONS
    ) == pytest.approx(1.0)


def test_weather_times_season():
    s = session(HOT, month=7)
    assert eb.get_environment_multiplier(
        s, monster("fire"), SEASONS
    ) == pytest.approx(1.32)


def test_multiplier_is_clamped():
    strong = [mod("fire", 2.0)]
    weak = [mod("fire", 0.1)]
    hot_summer = {"summer": [mod("fire", 2.0)]}
    assert (
        eb.get_environment_multiplier(
            session(strong, month=7), monster("fire"), hot_summer
        )
        == eb.MAX_ENVIRONMENT_MULTIPLIER
    )
    assert (
        eb.get_environment_multiplier(
            session(weak, month=7), monster("fire"), {}
        )
        == eb.MIN_ENVIRONMENT_MULTIPLIER
    )


def test_no_manager_or_weather():
    m = monster("water")
    assert eb.get_environment_multiplier(session(manager=False), m, {}) == 1
    assert eb.get_environment_multiplier(session(None), m, {}) == 1


def test_season_error_is_ignored():
    s = session(RAIN)
    s.time = MagicMock()
    s.time.get_time_variables.side_effect = ValueError("bad hemisphere")
    with patch.object(eb, "logger") as log:
        mult = eb.get_environment_multiplier(s, monster("water"), SEASONS)
    assert mult == pytest.approx(1.2)
    log.warning.assert_called_once()


def test_season_file_missing(tmp_path):
    with patch.object(eb, "logger") as log:
        assert eb.load_season_modifiers(tmp_path / "nope.yaml") == {}
    assert "not found" in log.warning.call_args.args[0]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("summer: fire\n", id="not_a_list"),
        pytest.param(
            "summer:\n  - attribute: colour\n    values: [fire]\n",
            id="bad_attribute",
        ),
        pytest.param(
            "summer:\n  - attribute: type\n    multiplier: 9\n",
            id="multiplier_out_of_range",
        ),
    ],
)
def test_season_file_invalid(tmp_path, content):
    path = tmp_path / "season_modifiers.yaml"
    path.write_text(content, encoding="utf-8")
    with patch.object(eb, "logger") as log:
        assert eb.load_season_modifiers(path) == {}
    assert "Invalid season modifiers file" in log.warning.call_args.args[0]


def test_apply_bonus():
    assert eb.apply_environment_bonus(100, 1.2) == 120
    assert eb.apply_environment_bonus(10, 0.85) == 8
    assert eb.apply_environment_bonus(1, 0.5) == 1
    assert eb.apply_environment_bonus(0, 1.5) == 0


# --- shipped data ----------------------------------------------------------


def element_slugs():
    return {load_yaml(p)["slug"] for p in (DB / "element").glob("*.yaml")}


def test_shipped_weather_modifiers():
    elements = element_slugs()
    weathers = {
        w["slug"]: WeatherModel.model_validate(w)
        for w in load_yaml(DB / "weather" / "weathers.yaml")
    }
    for weather in weathers.values():
        for m in weather.modifiers:
            assert m.attribute == "type"
            assert set(m.values) <= elements, weather.slug
    rain = {m.values[0]: m.multiplier for m in weathers["rain"].modifiers}
    assert rain == {"water": 1.2, "fire": 0.8}
    assert weathers["cloudy"].modifiers == []


def test_shipped_season_modifiers():
    seasons = eb.load_season_modifiers(eb.SEASON_MODIFIERS_FILE)
    assert set(seasons) == {"spring", "summer", "autumn", "winter"}
    elements = element_slugs()
    for mods in seasons.values():
        for m in mods:
            assert set(m.values) <= elements


# --- damage effects ----------------------------------------------------------


def combat_session(weather_mods, month=6):
    s = session(weather_mods, month=month)
    target = monster("earth")
    target.current_hp = 500
    cs = MagicMock()
    cs.get_tech_hit.return_value = 0.0
    cs.get_targets.return_value = [target]
    cs.get_own_monsters.return_value = [target]
    s.client.combat_session = cs
    return s, target


def tech():
    t = MagicMock()
    t.accuracy = 1.0
    t.name = "splash"
    return t


@pytest.mark.parametrize(
    "weather_mods,expected_hp,extras",
    [
        pytest.param([], 400, [], id="sunny_no_bonus"),
        pytest.param(RAIN, 380, [eb.BOOST_MESSAGE], id="rain_boost"),
        pytest.param(
            [mod("water", 0.5)], 450, [eb.WEAKEN_MESSAGE], id="weaken"
        ),
    ],
)
def test_damage_effect(weather_mods, expected_hp, extras):
    s, target = combat_session(weather_mods)
    user = monster("water")
    with (
        patch(
            "tuxemon.combat.environment_bonus._default_season_modifiers",
            return_value={},
        ),
        patch(
            "tuxemon.core.effects.damage.formula.simple_damage_calculate",
            return_value=(100, 2.0),
        ),
    ):
        result = DamageEffect().apply_tech_target(s, tech(), user, target)
    assert target.current_hp == expected_hp
    assert result.damage == 500 - expected_hp
    assert result.element_multiplier == 2.0
    assert result.extras == extras


def test_damage_effect_miss_has_no_message():
    s, target = combat_session(RAIN)
    s.client.combat_session.get_tech_hit.return_value = 1.0
    t = tech()
    t.accuracy = 0.0
    with patch(
        "tuxemon.core.effects.damage.formula.simple_damage_calculate",
        return_value=(100, 1.0),
    ) as calc:
        result = DamageEffect().apply_tech_target(
            s, t, monster("water"), target
        )
    calc.assert_not_called()
    assert result.damage == 0
    assert result.extras == []


def test_multiattack_effect():
    s, target = combat_session(RAIN)
    with (
        patch(
            "tuxemon.combat.environment_bonus._default_season_modifiers",
            return_value={},
        ),
        patch(
            "tuxemon.core.effects.multiattack.formula.simple_damage_calculate",
            return_value=(10, 1.0),
        ),
    ):
        result = MultiAttackEffect(times=3).apply_tech_target(
            s, tech(), monster("water"), target
        )
    assert result.hit_count == 3
    assert result.damage == 36
    assert eb.BOOST_MESSAGE in result.extras


def test_splash_effect():
    from tuxemon.core.effects.splash import SplashEffect

    s, target = combat_session(RAIN)
    with (
        patch(
            "tuxemon.combat.environment_bonus._default_season_modifiers",
            return_value={},
        ),
        patch(
            "tuxemon.core.effects.splash.formula.simple_damage_calculate",
            return_value=(50, 1.0),
        ),
    ):
        result = SplashEffect(divisor=2).apply_tech_target(
            s, tech(), monster("water"), target
        )
    assert result.damage == 60
    assert target.current_hp == 440
    assert result.element_multiplier == 1.0
    assert result.extras == [eb.BOOST_MESSAGE]
