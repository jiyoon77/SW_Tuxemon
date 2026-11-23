# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from unittest.mock import MagicMock

import pytest

from tuxemon import formula
from tuxemon.combat.session import CombatSession
from tuxemon.core.asset import init_assets
from tuxemon.core.core_effect import TechEffectResult
from tuxemon.database.runtime import db
from tuxemon.element import Element, ElementTypesHandler
from tuxemon.entity.npc import NPC
from tuxemon.monster.monster import Monster
from tuxemon.session import Session
from tuxemon.shape import Shape
from tuxemon.taste import Taste
from tuxemon.technique.technique import Technique


@pytest.fixture(scope="module")
def battle_assets():
    with pytest.MonkeyPatch.context() as patch:
        for table in ("element", "shape", "taste", "technique", "monster"):
            patch.setitem(db.database, table, {})
            db.load(table)
        patch.setattr(Element, "_elements", {})
        patch.setattr(ElementTypesHandler, "_multiplier_cache", {})
        patch.setattr(Shape, "_shapes", {})
        patch.setattr(Taste, "_tastes", {})
        init_assets()
        yield


@pytest.fixture
def battle(battle_assets):
    combat = CombatSession()
    session = Session()
    session.set_client(MagicMock(combat_session=combat))
    user = Monster.spawn_base("rockitten", 10)
    target = Monster.spawn_base("rockitten", 10)
    left = MagicMock(spec=NPC, monsters=[user])
    right = MagicMock(spec=NPC, monsters=[target])
    combat.set_players([left, right])
    combat.field_monsters.add_monster(left, user)
    combat.field_monsters.add_monster(right, target)
    combat.next_turn()
    combat.set_tech_hit(user, 0)
    return session, combat, user, target


def use_queued_technique(battle, technique):
    session, combat, user, target = battle
    combat.enqueue_action(user, technique, target)
    action = combat.action_queue.pop()
    result, _ = combat.apply_technique(
        session, action.method, action.user, action.target
    )
    return result


def test_hit_records_damage_before_result(battle):
    _, combat, user, target = battle
    technique = Technique.create("ram")
    hp_before = target.current_hp
    actor_name, target_name = user.name, target.name

    result = use_queued_technique(battle, technique)
    user.name = "Renamed attacker"
    target.name = "Renamed target"

    assert result.success
    damage, technique_result = combat.battle_log
    assert damage.event_type == "damage"
    assert damage.hp_change == target.current_hp - hp_before < 0
    assert technique_result.event_type == "technique_result"
    assert technique_result.hp_change is None
    assert [damage.sequence, technique_result.sequence] == [1, 2]
    for entry in combat.battle_log:
        assert entry.action_id == 1
        assert entry.turn == 1
        assert entry.outcome == "success"
        assert entry.actor_id == user.instance_id
        assert entry.target_id == target.instance_id
        assert entry.actor_name == actor_name
        assert entry.target_name == target_name
        assert entry.technique_slug == technique.slug
        assert entry.technique_name == technique.name
    assert combat.current_action_id is None


def test_miss_records_only_failed_result(battle):
    _, combat, user, target = battle
    technique = Technique.create("ram")
    technique.accuracy = 0.5
    combat.set_tech_hit(user, 1)
    hp_before = target.current_hp

    assert not use_queued_technique(battle, technique).success

    (entry,) = combat.battle_log
    assert entry.event_type == "technique_result"
    assert entry.outcome == "failure"
    assert target.current_hp == hp_before


def test_cancelled_queue_action_has_no_log(battle):
    _, combat, user, target = battle
    technique = Technique.create("ram")
    combat.enqueue_action(user, technique, target)
    (action,) = combat.action_queue.queue
    combat.action_queue.dequeue(action)

    assert combat.action_queue.is_empty()
    assert combat.battle_log == []
    assert technique.attempts == 0


def test_spread_damage_uses_ids_and_actual_hp_loss(battle, monkeypatch):
    _, combat, user, target = battle
    other_target = Monster.spawn_base("rockitten", 10)
    assert target.name == other_target.name
    assert target.instance_id != other_target.instance_id
    combat.set_battle_format(True)
    combat.right_player.monsters.append(other_target)
    combat.field_monsters.add_monster(combat.right_player, other_target)
    target.current_hp = 7
    other_target.current_hp = 23
    technique = Technique.create("ram")
    technique.target["enemy_monster"] = False
    technique.target["enemy_team"] = True
    monkeypatch.setattr(
        formula, "simple_damage_calculate", lambda *_: (27, 1.0)
    )

    result = use_queued_technique(battle, technique)

    first, second, technique_result = combat.battle_log
    assert [first.event_type, second.event_type] == ["damage", "damage"]
    assert {entry.target_name for entry in (first, second)} == {target.name}
    assert {entry.target_id: entry.hp_change for entry in (first, second)} == {
        target.instance_id: -7,
        other_target.instance_id: -20,
    }
    assert target.current_hp == 0
    assert other_target.current_hp == 3
    assert technique_result.event_type == "technique_result"
    assert {entry.action_id for entry in combat.battle_log} == {1}
    assert [entry.sequence for entry in combat.battle_log] == [1, 2, 3]
    assert result.damage == 20
    (reward_damage,) = combat.damage_tracker.get_damages(user, other_target)
    assert reward_damage.damage == 20


def test_zero_hp_change_has_no_damage_event(battle, monkeypatch):
    _, combat, _, _ = battle
    monkeypatch.setattr(
        formula, "simple_damage_calculate", lambda *_: (0, 1.0)
    )

    assert not use_queued_technique(battle, Technique.create("ram")).success

    (entry,) = combat.battle_log
    assert entry.event_type == "technique_result"


def test_action_ids_and_sequences_restart_after_reset(battle):
    _, combat, user, _ = battle
    technique = Technique.create("ram")
    technique.accuracy = 0.5
    combat.set_tech_hit(user, 1)
    use_queued_technique(battle, technique)
    combat.next_turn()
    use_queued_technique(battle, technique)

    assert [entry.action_id for entry in combat.battle_log] == [1, 2]
    assert [entry.sequence for entry in combat.battle_log] == [1, 2]
    assert [entry.turn for entry in combat.battle_log] == [1, 2]

    combat.reset()

    assert combat.battle_log == []
    assert combat.current_action_id is None
    combat.next_turn()
    combat.set_tech_hit(user, 1)
    use_queued_technique(battle, technique)

    (entry,) = combat.battle_log
    assert (entry.turn, entry.action_id, entry.sequence) == (1, 1, 1)


def test_exception_clears_action_id_and_direct_damage_stays_unlogged(
    battle, monkeypatch
):
    session, combat, user, target = battle
    broken_technique = Technique.create("ram")

    def fail(*args):
        assert combat.current_action_id is not None
        raise RuntimeError("technique failed")

    monkeypatch.setattr(broken_technique, "use", fail)
    with pytest.raises(RuntimeError, match="technique failed"):
        use_queued_technique(battle, broken_technique)

    assert combat.current_action_id is None
    assert combat.battle_log == []
    assert Technique.create("ram").use(session, user, target).success
    assert combat.battle_log == []


@pytest.mark.parametrize(
    "slug",
    [
        pytest.param("swap", id="swap"),
        pytest.param("menu_run", id="run"),
        pytest.param("menu_forfeit", id="forfeit"),
    ],
)
def test_combat_menu_actions_are_excluded(battle, monkeypatch, slug):
    _, combat, _, _ = battle
    technique = Technique.create(slug)

    def use(*args):
        assert combat.current_action_id is None
        return TechEffectResult(name=technique.name, success=True)

    monkeypatch.setattr(technique, "use", use)

    assert use_queued_technique(battle, technique).success
    assert combat.battle_log == []
