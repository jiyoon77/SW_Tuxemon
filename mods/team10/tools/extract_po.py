# SPDX-License-Identifier: GPL-3.0
# team10: Korean translation helper for Tuxemon .po files.
"""
Usage:
    python mods/team10/tools/extract_po.py extract  <src.po> <out.po> menu_ combat_
    python mods/team10/tools/extract_po.py check    <en.po>  <ko.po>
    python mods/team10/tools/extract_po.py missing  <en.po>  <ko.po> menu_ combat_
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ENTRY = re.compile(
    r'msgid "((?:[^"\\]|\\.)*)"\nmsgstr ((?:"(?:[^"\\]|\\.)*"\n?)+)'
)
PIECE = re.compile(r'"((?:[^"\\]|\\.)*)"')
PLACEHOLDER = re.compile(r"\{[a-zA-Z0-9_]+\}")


def read_po(path: str) -> dict[str, str]:
    """Return {msgid: msgstr} for every non-header entry in a .po file."""
    text = Path(path).read_text(encoding="utf-8")
    entries = {}
    for msgid, raw in ENTRY.findall(text):
        if msgid:
            entries[msgid] = "".join(PIECE.findall(raw))
    return entries


def extract(src_po: str, prefixes: list[str], out_po: str) -> int:
    """Write the entries whose msgid starts with one of the prefixes."""
    entries = read_po(src_po)
    picked = {k: v for k, v in entries.items() if k.startswith(tuple(prefixes))}
    lines = []
    for key, value in picked.items():
        lines.append(f'# en: {value}\nmsgid "{key}"\nmsgstr ""\n')
    Path(out_po).write_text("\n".join(lines), encoding="utf-8")
    return len(picked)


def check_placeholders(en_po: str, ko_po: str) -> list[str]:
    """List msgids whose translation lost or added a {placeholder}."""
    en, ko = read_po(en_po), read_po(ko_po)
    problems = []
    for key, value in ko.items():
        if not value or key not in en:
            continue
        if sorted(PLACEHOLDER.findall(en[key])) != sorted(PLACEHOLDER.findall(value)):
            problems.append(key)
    return problems


def report_missing(en_po: str, ko_po: str, prefixes: list[str]) -> list[str]:
    """List msgids in scope that have no Korean translation yet."""
    en, ko = read_po(en_po), read_po(ko_po)
    return [
        k
        for k in en
        if k.startswith(tuple(prefixes)) and not ko.get(k)
    ]


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    if cmd == "extract":
        print(extract(args[0], args[2:], args[1]), "entries written")
    elif cmd == "check":
        bad = check_placeholders(args[0], args[1])
        print("\n".join(bad) or "placeholders OK")
        sys.exit(1 if bad else 0)
    elif cmd == "missing":
        left = report_missing(args[0], args[1], args[2:])
        print("\n".join(left))
        print(len(left), "missing")
