# SPDX-License-Identifier: GPL-3.0
from types import SimpleNamespace
from unittest.mock import Mock

import pygame

from tuxemon.base_client import BaseClient
from tuxemon.combat.machine import CombatPhase
from tuxemon.combat.session import CombatSession
from tuxemon.config import TuxemonConfig
from tuxemon.event.eventbus import EventBus
from tuxemon.menu.alert import AlertManager
from tuxemon.platform.platform_pygame.events import PygameKeyboardInput
from tuxemon.scaling import DefaultScaling
from tuxemon.state.state import State
from tuxemon.states.combat_state import CombatState
from tuxemon.ui.combat_notifier import TextAnimationManager
from tuxemon.ui.text import TextArea


def make_combat(config: TuxemonConfig) -> CombatState:
    combat = CombatState.__new__(CombatState)
    client = SimpleNamespace(
        config=config,
        context=SimpleNamespace(resolution=(800, 600)),
        event_bus=EventBus(),
    )
    State.__init__(combat, client)
    combat.combat_session = CombatSession()
    combat.phase = CombatPhase.BEGIN
    combat.text_anim = TextAnimationManager()
    combat.update_speed_label = Mock()
    combat.update_combat_phase = Mock()
    return combat


def test_tab_cycles_and_saves_speed_without_repeating(tmp_path):
    config_path = tmp_path / "tuxemon.yaml"
    config = TuxemonConfig(config_path)
    combat = make_combat(config)
    keyboard = PygameKeyboardInput(config.input.keyboard_button_map)
    client = SimpleNamespace(_active_combat=lambda: combat)

    for expected in (2, 4, 1):
        keyboard.process_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB)
        )
        list(BaseClient._battle_speed_events(client, keyboard.get_events()))
        assert combat.effective_battle_speed == expected
        assert TuxemonConfig(config_path).battle_speed == expected

        list(BaseClient._battle_speed_events(client, keyboard.get_events()))
        assert combat.effective_battle_speed == expected
        keyboard.process_event(
            pygame.event.Event(pygame.KEYUP, key=pygame.K_TAB)
        )


def test_pvp_uses_normal_speed_and_keeps_saved_preference():
    config = TuxemonConfig()
    config.update_attribute("gameplay", "battle_speed", 4, save=False)
    combat = make_combat(config)
    combat.combat_session.is_pvp = True

    combat.cycle_battle_speed()

    assert combat.effective_battle_speed == 1
    assert config.battle_speed == 4
    combat.combat_session.reset()
    assert combat.effective_battle_speed == 4


def test_4x_preserves_task_order_and_does_not_repeat_callbacks():
    def run(speed, frames):
        config = TuxemonConfig()
        config.update_attribute("gameplay", "battle_speed", speed, save=False)
        combat = make_combat(config)
        calls = []
        # Tasks can be added out of deadline order by combat animations.
        combat.task(lambda: calls.append("capture"), interval=0.375)
        combat.task(lambda: calls.append("swap"), interval=0.125)
        combat.task(lambda: calls.append("hp"), interval=0.25)
        for _ in range(frames):
            combat.update(0.125)
        return calls

    assert run(4, 2) == run(1, 8) == ["swap", "hp", "capture"]


def test_only_the_combat_text_area_is_accelerated():
    def make_area():
        return TextArea(
            font=pygame.font.Font(None, 16),
            font_color=(255, 255, 255),
            rect=pygame.Rect(0, 0, 200, 50),
            scaling=DefaultScaling(1),
        )

    normal_area, combat_area = make_area(), make_area()
    alert = AlertManager(EventBus())
    alert.alert("A", normal_area, dialog_speed="slow")
    alert.update(0.025, accelerated_area=combat_area, text_speed_multiplier=4)
    assert normal_area.drawing_text
    alert.dump_remaining_text(normal_area)

    alert.alert("A", combat_area, dialog_speed="slow")
    alert.update(0.025, accelerated_area=combat_area, text_speed_multiplier=4)
    assert not combat_area.drawing_text
