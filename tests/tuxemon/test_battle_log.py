# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from datetime import datetime
from functools import partial
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from tuxemon import formula
from tuxemon.combat.session import CombatSession
from tuxemon.core.asset import init_assets
from tuxemon.core.core_effect import TechEffectResult
from tuxemon.database.runtime import db
from tuxemon.element import Element, ElementTypesHandler
from tuxemon.entity.npc import NPC
from tuxemon.item.item import Item
from tuxemon.monster.monster import Monster
from tuxemon.session import Session
from tuxemon.shape import Shape
from tuxemon.states.combat_state import CombatPhase, CombatState
from tuxemon.status.status import Status
from tuxemon.taste import Taste
from tuxemon.technique.technique import Technique


@pytest.fixture(scope="module")
def battle_assets():
    with pytest.MonkeyPatch.context() as patch:
        for table in (
            "element",
            "shape",
            "taste",
            "technique",
            "monster",
            "item",
            "status",
        ):
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
    session.set_client(MagicMock(combat_session=combat, weather_manager=None))
    user = Monster.spawn_base("rockitten", 10)
    target = Monster.spawn_base("rockitten", 10)
    left = MagicMock(spec=NPC, monsters=[user], instance_id=uuid4())
    right = MagicMock(spec=NPC, monsters=[target], instance_id=uuid4())
    left.name, right.name = "Left trainer", "Right trainer"
    left.is_player = right.is_player = False
    left.party = MagicMock(is_fainted=False)
    right.party = MagicMock(is_fainted=False)
    left.bag, right.bag = MagicMock(), MagicMock()
    left.tuxepedia = MagicMock()
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


@pytest.mark.parametrize(
    "slug",
    [
        pytest.param("mending", id="direct"),
        pytest.param("healing_herb", id="proportional"),
        pytest.param("solar_synthesis", id="time-of-day"),
    ],
)
def test_healing_technique_records_only_actual_recovery(
    battle, monkeypatch, slug
):
    session, combat, user, _ = battle
    session.client.map_manager.map_inside = False
    monkeypatch.setattr(
        session.time, "get_current_time", lambda: datetime(2026, 10, 15, 12)
    )
    healing_action = (session, combat, user, user)
    hp_before = user.hp - 2
    user.current_hp = hp_before

    assert use_queued_technique(healing_action, Technique.create(slug)).success
    healing, result = combat.battle_log
    assert healing.event_type == "healing"
    assert healing.hp_change == user.current_hp - hp_before == 2
    assert healing.actor_id == healing.target_id == user.instance_id
    assert result.action_id == healing.action_id == 1

    use_queued_technique(healing_action, Technique.create(slug))
    assert user.current_hp == user.hp
    assert [entry.event_type for entry in combat.battle_log] == [
        "healing",
        "technique_result",
        "technique_result",
    ]


def test_status_application_stack_block_and_item_removal(battle):
    session, combat, user, target = battle
    target.current_hp -= 3
    use_queued_technique(battle, Technique.create("poison_courtship"))
    poison = target.status.current_status
    assert poison and poison.slug == "poison"
    use_queued_technique(battle, Technique.create("poison_courtship"))
    assert poison.lifecycle.stack_level == 2
    assert target.item_handler.set_item(Item.create("antidote_grapes"))
    use_queued_technique(battle, Technique.create("poison_courtship"))
    assert poison.lifecycle.stack_level == 2

    item = Item.create("cureall")
    assert combat.apply_item(
        session, item, combat.right_player, target
    ).success
    assert target.current_hp == target.hp and not target.status.status_exists()
    applied, _, stacked, _, blocked, _, healing, removed, item_result = (
        combat.battle_log
    )
    assert [
        entry.event_type
        for entry in (applied, stacked, blocked, healing, removed, item_result)
    ] == [
        "status_applied",
        "status_stacked",
        "status_blocked",
        "healing",
        "status_removed",
        "item_result",
    ]
    assert [
        entry.action_id for entry in (applied, stacked, blocked, removed)
    ] == [1, 2, 3, 4]
    assert {
        entry.status_slug for entry in (applied, stacked, blocked, removed)
    } == {"poison"}
    assert (
        blocked.outcome == "failure"
        and blocked.blocked_by == target.held_item.name
    )
    assert stacked.actor_id == user.instance_id
    assert removed.actor_id == combat.right_player.instance_id
    assert {entry.item_slug for entry in (healing, removed, item_result)} == {
        item.slug
    }
    assert {entry.action_id for entry in (healing, removed, item_result)} == {
        4
    }
    assert {entry.target_id for entry in (healing, removed, item_result)} == {
        target.instance_id
    }
    assert healing.hp_change == 3 and item_result.hp_change is None
    assert [entry.sequence for entry in combat.battle_log] == list(
        range(1, 10)
    )


@pytest.mark.parametrize(
    "slug, expected_user, expected_target",
    [
        pytest.param("data_swap", 15, 15, id="average"),
        pytest.param("kiss", 20, 10, id="swap"),
    ],
)
def test_hp_redistribution_records_damage_and_healing(
    battle, slug, expected_user, expected_target
):
    _, combat, user, target = battle
    user.current_hp, target.current_hp = 10, 20

    assert use_queued_technique(battle, Technique.create(slug)).success

    assert (user.current_hp, target.current_hp) == (
        expected_user,
        expected_target,
    )
    *effects, result = combat.battle_log
    assert len(effects) == 2
    assert {
        entry.target_id: (entry.event_type, entry.hp_change)
        for entry in effects
    } == {
        user.instance_id: ("healing", expected_user - 10),
        target.instance_id: ("damage", expected_target - 20),
    }
    assert {entry.actor_id for entry in combat.battle_log} == {
        user.instance_id
    }
    assert {entry.action_id for entry in combat.battle_log} == {
        result.action_id
    }


def test_leech_status_records_both_monsters_actual_hp_change(battle):
    _, combat, user, target = battle
    state = combat_state(battle)
    status = Status.create("lifeleech", target)
    status.set_linked_monster(user)
    target.status.add_status(status)
    user.current_hp = user.hp - 1
    user_before, target_before = user.current_hp, target.current_hp

    CombatState._handle_status(state, status, target)

    damage, healing = combat.battle_log
    assert (damage.event_type, healing.event_type) == (
        "status_damage",
        "healing",
    )
    assert damage.hp_change == target.current_hp - target_before < 0
    assert healing.hp_change == user.current_hp - user_before == 1
    assert (
        damage.target_id == target.instance_id
        and healing.target_id == user.instance_id
    )
    assert damage.actor_id == healing.actor_id == user.instance_id
    assert damage.action_id == healing.action_id == 1


def test_multiattack_reward_uses_calculated_damage(battle, monkeypatch):
    _, combat, user, target = battle
    state = combat_state(battle)
    target.current_hp = 7
    monkeypatch.setattr("tuxemon.combat.session.random.random", lambda: 0)
    monkeypatch.setattr(
        formula, "simple_damage_calculate", lambda *_: (10, 1.0)
    )
    monkeypatch.setattr(
        "tuxemon.core.effects.multiattack.get_environment_multiplier",
        lambda *_: 1.0,
    )

    CombatState._handle_monster_technique(
        state, user, Technique.create("one_two"), target
    )

    assert target.current_hp == 0
    damage, summary = combat.battle_log
    assert damage.hp_change == -7 and damage.hit_count == 2
    assert damage.action_id == summary.action_id
    (reward_damage,) = combat.damage_tracker.get_damages(user, target)
    assert reward_damage.damage == 20


def test_blocked_potion_records_failure_without_healing(battle):
    session, combat, user, _ = battle
    user.status.add_status(Status.create("festering", user))
    user.current_hp -= 3
    hp_before = user.current_hp
    item = Item.create("potion")

    assert not combat.apply_item(
        session, item, combat.left_player, user
    ).success

    (result,) = combat.battle_log
    assert result.event_type == "item_result" and result.outcome == "failure"
    assert result.item_name == item.name and result.hp_change is None
    assert result.target_id == user.instance_id
    assert user.current_hp == hp_before


def test_technique_follow_up_status_is_recorded_in_same_action(battle):
    _, combat, user, _ = battle
    user.status.add_status(Status.create("chargedup", user))

    assert use_queued_technique(battle, Technique.create("ram")).success

    assert user.status.current_status.slug == "exhausted"
    assert user.status.current_status.lifecycle.stack_level == 2
    damage, removed, applied, stacked, result = combat.battle_log
    assert [
        entry.event_type
        for entry in (damage, removed, applied, stacked, result)
    ] == [
        "damage",
        "status_removed",
        "status_applied",
        "status_stacked",
        "technique_result",
    ]
    assert [entry.status_slug for entry in (removed, applied, stacked)] == [
        "chargedup",
        "exhausted",
        "exhausted",
    ]
    assert {entry.action_id for entry in combat.battle_log} == {1}


def combat_state(battle):
    session, combat, _, _ = battle
    state = MagicMock(session=session, combat_session=combat)
    state.text_anim.compute_text_anim_time.return_value = 0.0
    state.animate_monster_faint.side_effect = partial(
        CombatState.animate_monster_faint, state
    )
    state.apply_status_effects.side_effect = partial(
        CombatState.apply_status_effects, state
    )
    state.handle_monster_defeat.side_effect = partial(
        CombatState.handle_monster_defeat, state
    )
    return state


@pytest.mark.parametrize(
    "slug",
    [pytest.param("poison", id="poison"), pytest.param("burn", id="burn")],
)
def test_turn_boundary_damage_and_faint_belong_to_status(battle, slug):
    _, combat, user, target = battle
    state = combat_state(battle)
    status = Status.create(slug, target)
    target.status.add_status(status)
    CombatState._handle_monster_technique(
        state, user, Technique.create("ram"), target
    )
    (reward_damage,) = combat.damage_tracker.get_damages(user, target)
    assert reward_damage.damage > 0
    attack, summary = combat.battle_log
    assert attack.hp_change < 0 and attack.actor_id == user.instance_id
    assert target.current_hp > 0
    target.current_hp = 1
    combat.next_turn()

    CombatState.transition_phase(state, CombatPhase.POST_ACTION)
    action = combat.action_queue.pop()
    assert action.method is status and action.target is target
    CombatState._handle_status(state, action.method, action.target)
    CombatState.check_party_hp(state)
    CombatState.animate_party_status(state)
    CombatState.animate_party_status(state)

    assert target.current_hp == 0
    assert combat.damage_tracker.get_damages(user, target) == []
    tick, faint = combat.battle_log[2:]
    assert (tick.event_type, faint.event_type) == ("status_damage", "faint")
    assert tick.hp_change == -1 and faint.hp_change is None
    assert tick.status_slug == faint.status_slug == slug
    assert tick.actor_id is faint.actor_id is None
    assert tick.technique_slug is faint.technique_slug is None
    assert tick.target_id == faint.target_id == target.instance_id
    assert tick.action_id == faint.action_id != summary.action_id
    assert tick.turn == faint.turn == 2
    assert [entry.sequence for entry in combat.battle_log] == [1, 2, 3, 4]
    assert combat.current_action_id is None


def test_diehard_recovery_prevents_faint_and_clears_previous_cause(battle):
    _, combat, user, target = battle
    state = combat_state(battle)
    target.status.add_status(Status.create("diehard", target))
    target.current_hp = 2

    use_queued_technique(battle, Technique.create("ram"))
    assert target.current_hp == 0
    CombatState.check_party_hp(state)
    CombatState.animate_party_status(state)
    assert target.current_hp == 1
    assert [entry.event_type for entry in combat.battle_log] == [
        "damage",
        "technique_result",
        "healing",
        "status_removed",
    ]
    assert combat.battle_log[2].hp_change == 1

    use_queued_technique(battle, Technique.create("ram"))
    CombatState.check_party_hp(state)
    CombatState.animate_party_status(state)
    second_damage, result, faint = combat.battle_log[-3:]
    assert second_damage.hp_change == -1
    assert faint.event_type == "faint"
    assert faint.action_id == result.action_id == second_damage.action_id
    assert faint.actor_id == user.instance_id


@pytest.mark.parametrize(
    "success",
    [pytest.param(True, id="caught"), pytest.param(False, id="escaped")],
)
def test_capture_has_one_result_before_animation_callback(
    battle, monkeypatch, success
):
    session, combat, _, target = battle
    state = combat_state(battle)
    trainer = combat.left_player
    session.set_player(trainer)
    target.set_owner(combat.right_player)
    target.wild = True
    monkeypatch.setattr(formula, "shake_check", lambda *_: 100)
    monkeypatch.setattr(
        formula.random, "randint", lambda *_: 0 if success else 101
    )
    item = Item.create("tuxeball")

    result = combat.apply_item(session, item, trainer, target)

    assert target.wild is not success
    assert result.success is success
    capture, item_result = combat.battle_log
    assert (capture.event_type, item_result.event_type) == (
        "capture_result",
        "item_result",
    )
    assert (
        capture.outcome
        == item_result.outcome
        == ("success" if success else "failure")
    )
    assert capture.num_shakes == result.num_shakes
    assert capture.item_slug == item_result.item_slug == item.slug
    assert capture.actor_id == item_result.actor_id == trainer.instance_id
    assert capture.target_id == item_result.target_id == target.instance_id
    assert capture.action_id == item_result.action_id == 1
    assert trainer.party.add_monster.call_count == int(success)
    reset = combat.reset

    def check_then_reset():
        assert combat.battle_log == [capture, item_result]
        reset()

    monkeypatch.setattr(combat, "reset", check_then_reset)
    CombatState._on_capture_finished(state, target, success)
    assert combat.battle_log == ([] if success else [capture, item_result])


@pytest.mark.parametrize(
    "hazard",
    [
        pytest.param(False, id="regular"),
        pytest.param(True, id="fainted-outgoing"),
    ],
)
def test_swap_logs_after_replacement_joins_field(battle, hazard):
    session, combat, user, _ = battle
    if hazard:
        user.current_hp = 1
        user.status.add_status(Status.create("harpooned", user))
    state = combat_state(battle)
    player = combat.left_player
    user.set_owner(player)
    incoming = Monster.spawn_base("rockitten", 10)
    player.monsters.append(incoming)
    callbacks = []
    state.task.side_effect = lambda callback, **_: callbacks.append(callback)

    def publish(event, **kwargs):
        if event == "monster_swapped_out":
            CombatState.remove_monster_from_play(state, kwargs["monster"])
        elif event == "monster_swapped_in":
            CombatState._on_monster_swapped_in(state, **kwargs)

    session.client.event_bus.publish.side_effect = publish
    combat.enqueue_action(user, Technique.create("swap"), incoming)
    action = combat.action_queue.pop()
    result, _ = combat.apply_technique(
        session, action.method, action.user, action.target
    )

    assert result.success and combat.battle_log == []
    assert incoming not in combat.active_monsters
    callbacks[-1]()
    assert (
        incoming in combat.active_monsters
        and user not in combat.active_monsters
    )
    swap, *effects = combat.battle_log
    assert swap.event_type == "swap"
    assert (
        swap.actor_id == user.instance_id
        and swap.target_id == incoming.instance_id
    )
    assert swap.action_id == swap.sequence == 1
    if hazard:
        damage, faint = effects
        assert (damage.event_type, faint.event_type) == (
            "status_damage",
            "faint",
        )
        assert damage.hp_change == -1 and user.current_hp == 0
        assert damage.status_slug == faint.status_slug == "harpooned"
        assert damage.target_id == faint.target_id == user.instance_id
        assert damage.action_id == faint.action_id == swap.action_id
        CombatState.animate_party_status(state)
        assert combat.battle_log == [swap, damage, faint]
    else:
        assert effects == []


def test_forced_replacement_records_trainer_and_incoming_monster(battle):
    session, combat, _, _ = battle
    state = combat_state(battle)
    player = combat.right_player
    incoming = Monster.spawn_base("rockitten", 10)
    player.monsters.append(incoming)
    state.ai_manager.choose_replacement_monster.return_value = incoming
    player.party.alive = player.monsters
    combat.field_monsters.remove_monster(player, player.monsters[0])

    CombatState._on_monster_needed(state, player)
    assert combat.battle_log == []

    combat.field_monsters.remove_monster(player, incoming)
    combat.field_monsters.remove_monster(player, player.monsters[0])
    combat.next_turn()
    CombatState._on_monster_needed(state, player, ask=True)

    (replacement,) = combat.battle_log
    assert replacement.event_type == "replacement" and replacement.turn == 2
    assert replacement.actor_id == player.instance_id
    assert replacement.target_id == incoming.instance_id
    assert combat.field_monsters.get_monsters(player) == [incoming]


def test_spread_damage_uses_ids_and_actual_hp_loss(battle, monkeypatch):
    session, combat, user, target = battle
    monkeypatch.setattr(session.time, "hemisphere", "northern")
    monkeypatch.setattr(
        session.time, "get_current_time", lambda: datetime(2026, 10, 15, 12)
    )
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
        other_target.instance_id: -21,
    }
    assert target.current_hp == 0
    assert other_target.current_hp == 2
    assert technique_result.event_type == "technique_result"
    assert {entry.action_id for entry in combat.battle_log} == {1}
    assert [entry.sequence for entry in combat.battle_log] == [1, 2, 3]
    assert result.damage == 21
    (reward_damage,) = combat.damage_tracker.get_damages(user, other_target)
    assert reward_damage.damage == 21


@pytest.mark.parametrize(
    "roll, expected_damage",
    [pytest.param(0, 24, id="full-hit"), pytest.param(1, 3, id="partial-hit")],
)
def test_flow_records_actual_splash_per_target(
    battle, monkeypatch, roll, expected_damage
):
    _, combat, user, target = battle
    other = Monster.spawn_base("rockitten", 10)
    combat.set_battle_format(True)
    combat.right_player.monsters.append(other)
    combat.field_monsters.add_monster(combat.right_player, other)
    technique = Technique.create("flow")
    technique.target["enemy_monster"] = False
    technique.target["enemy_team"] = True
    combat.set_tech_hit(user, roll)
    target.current_hp = 2
    other_before = other.current_hp
    monkeypatch.setattr(
        formula, "simple_damage_calculate", lambda *_: (32, 1.0)
    )
    monkeypatch.setattr(
        "tuxemon.core.effects.splash.get_environment_multiplier",
        lambda *_: 1.0,
    )

    result = use_queued_technique(battle, technique)

    assert result.success and result.damage == expected_damage
    assert ("combat_splash_partial" in result.extras) == bool(roll)
    *damage, summary = combat.battle_log
    assert len(damage) == 2
    assert {entry.target_id: entry.hp_change for entry in damage} == {
        target.instance_id: target.current_hp - 2,
        other.instance_id: other.current_hp - other_before,
    }
    assert target.current_hp == 0
    assert other.current_hp == other_before - expected_damage
    assert summary.event_type == "technique_result"
    assert {entry.action_id for entry in combat.battle_log} == {1}
    (reward_damage,) = combat.damage_tracker.get_damages(user, other)
    assert reward_damage.damage == expected_damage


@pytest.mark.parametrize(
    "per_hit, rolls, expected_hits",
    [
        pytest.param(0, [0, 0], 2, id="zero-damage"),
        pytest.param(10, [0, 0], 2, id="overkill"),
        pytest.param(4, [0, 1], 1, id="second-hit-misses"),
    ],
)
def test_multiattack_records_hit_count_and_actual_total(
    battle, monkeypatch, per_hit, rolls, expected_hits
):
    _, combat, user, target = battle
    technique = Technique.create("one_two")
    target.current_hp = 7
    hit_rolls = iter(rolls)
    monkeypatch.setattr(
        "tuxemon.combat.session.random.random", lambda: next(hit_rolls)
    )
    monkeypatch.setattr(
        formula, "simple_damage_calculate", lambda *_: (per_hit, 1.0)
    )
    monkeypatch.setattr(
        "tuxemon.core.effects.multiattack.get_environment_multiplier",
        lambda *_: 1.0,
    )

    result = use_queued_technique(battle, technique)

    calculated_damage = per_hit * expected_hits
    actual = min(7, calculated_damage)
    assert result.success and result.damage == calculated_damage
    damage, summary = combat.battle_log
    assert damage.event_type == "damage" and damage.hit_count == expected_hits
    assert damage.hp_change == target.current_hp - 7 == -actual
    assert damage.action_id == summary.action_id == 1
    assert damage.actor_id == user.instance_id
    assert damage.target_id == summary.target_id == target.instance_id
    assert damage.sequence < summary.sequence


def test_tooth_for_tooth_records_self_and_enemy_damage(battle):
    _, combat, user, target = battle
    user.current_hp, target.current_hp = 5, 7

    result = use_queued_technique(battle, Technique.create("tooth_for_tooth"))

    assert result.success
    recoil, enemy_damage, summary = combat.battle_log
    assert recoil.event_type == enemy_damage.event_type == "damage"
    assert recoil.actor_id == recoil.target_id == user.instance_id
    assert enemy_damage.actor_id == user.instance_id
    assert enemy_damage.target_id == target.instance_id
    assert recoil.hp_change == user.current_hp - 5 == -5
    assert enemy_damage.hp_change == target.current_hp - 7 == -7
    assert recoil.action_id == enemy_damage.action_id == summary.action_id == 1
    (reward_damage,) = combat.damage_tracker.get_damages(user, user)
    assert reward_damage.damage == target.hp // 2


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
