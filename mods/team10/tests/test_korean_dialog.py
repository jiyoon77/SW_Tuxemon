# SPDX-License-Identifier: GPL-3.0
# team10: PR #12 review 3 - the dialog box showed only the end of a line
# ("성해 주세요." for "이 신청서만 작성해 주세요."), with the left side blank.
from __future__ import annotations

import os
from types import SimpleNamespace

import pygame
import pytest
from babel.messages.pofile import read_po
from pygame.rect import Rect

from tuxemon.constants import paths
from tuxemon.menu.alert import AlertManager
from tuxemon.menu.controller import MenuController
from tuxemon.platform.const import buttons
from tuxemon.platform.events import PlayerInput
from tuxemon.states.dialog_state import DialogState
from tuxemon.ui.text import TextArea

RECT = Rect(0, 0, 900, 120)


def _po(locale):
    path = paths.mods_folder / "tuxemon" / "l18n" / locale / "LC_MESSAGES" / "base.po"
    with open(path, "rb") as f:
        return {m.id: m.string for m in read_po(f) if m.id and m.string}


KO = _po("ko_KR")
EN = _po("en_US")
LINES = [
    KO["spyder_intro_shopkeeper2"],  # the line from the screenshot
    KO["spyder_intro_shopkeeper1"],
    KO["spyder_intro_question_name"],
    KO["spyder_intro_shopkeeper3"],
    EN["spyder_intro_shopkeeper2"],  # same in English
]


class _Scaling:
    def scale_int(self, value):
        return int(value * 3)

    def scale_sequence(self, seq):
        return [v * 3 for v in seq]


@pytest.fixture(scope="module", autouse=True)
def _pygame():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    pygame.display.set_mode((1, 1))
    yield


def make_dialog(text):
    """A real DialogState (TextArea + AlertManager) without a running client."""
    font = pygame.font.Font(str(paths.mods_folder / "tuxemon" / "font" / "NanumGothic-Bold.ttf"), 24)
    state = object.__new__(DialogState)
    state.text_queue = [text]
    state.avatar = None
    state.auto_close = True
    state.close_after = None
    state.per_line_timeout = False
    state.advance_buttons = [buttons.A]
    state.dialog_speed = "slow"
    state._elapsed_time = 0.0
    state._timer_active = False
    state.dialog_box = TextArea(font, (0, 0, 0), RECT, _Scaling(), font_shadow=(200, 200, 200))
    state.state_controller = MenuController()
    state.calc_internal_rect = lambda: RECT.copy()
    state.calc_final_rect = lambda: RECT.copy()
    state.close = lambda: None
    bus = SimpleNamespace(publish=lambda *a, **k: None)
    state.client = SimpleNamespace(event_bus=bus, alert_manager=AlertManager(bus))  # state.dialog
    return state


def finish_opening(state):
    """What Menu.resume's show_items() does when the open animation ends."""
    state.state_controller.set_normal()
    DialogState.on_open(state)


def draw_all(state):
    for _ in range(400):
        state.dialog.update(0.05)
    return pygame.image.tobytes(state.dialog_box.image, "RGBA")


@pytest.mark.parametrize("text", LINES)
def test_press_while_dialog_opens_keeps_whole_line(text):
    # expected: the window opens, then the text is typed out
    normal = make_dialog(text)
    normal.state_controller.open()
    finish_opening(normal)
    expected = draw_all(normal)

    # the player presses A (e.g. still advancing the previous dialog)
    # while this window is playing its open animation
    early = make_dialog(text)
    early.state_controller.open()
    early.process_event(PlayerInput(buttons.A, value=1, hold_time=1))  # a fresh press
    for _ in range(8):  # a few characters get typed during the animation
        early.dialog.update(0.05)
    finish_opening(early)

    assert draw_all(early) == expected


def test_press_after_opening_still_fast_forwards():
    state = make_dialog(LINES[0])
    state.state_controller.open()
    finish_opening(state)
    state.dialog.update(0.05)  # one character typed
    assert state.dialog_box.drawing_text
    state.process_event(PlayerInput(buttons.A, value=1, hold_time=1))
    assert not state.dialog_box.drawing_text  # whole line shown at once
    expected = make_dialog(LINES[0])
    expected.state_controller.open()
    finish_opening(expected)
    assert pygame.image.tobytes(state.dialog_box.image, "RGBA") == draw_all(expected)
