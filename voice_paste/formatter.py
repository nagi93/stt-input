"""Deterministic Japanese dictation formatter.

Turns a raw Haas-ja transcript into text that is pleasant to paste:

* filler words spoken at clause starts are dropped
  (えーと / あのー / そのー / えっと / うーん / なんか / まあ)
* spoken punctuation commands are applied:
    くてん            -> 。
    とうてん          -> 、
    かいぎょう / 改行  -> newline
    くうぎょう / 空行  -> blank line
  and, when they are isolated by punctuation / whitespace / string edges,
    まる -> 。   てん -> 、
  Set ``aggressive_commands=True`` to also convert まる/てん when they sit
  directly between other characters.  That catches "…ですまる明日…" but can
  misfire on words that merely contain those sounds, so it is off by default.
* punctuation is normalised (half-width ?! -> full-width, repeated marks
  collapsed, spaces between Japanese characters removed)
* a missing sentence-final 。 is added for plain statements

Everything here is pure stdlib and platform independent so it can be unit
tested anywhere.  An optional LLM polish hook lives in ``polish.py``; this
module never calls the network.
"""
from __future__ import annotations

import re

# Strong fillers: removable at a clause start whatever follows.
_FILLERS_STRONG = [
    "えーっと", "えーと", "えっと", "ええと", "あのー", "そのー",
    "うーんと", "うーん", "なんか", "まあ", "まぁ",
]
_FILLERS_STRONG.sort(key=len, reverse=True)  # えーっと must win over えーと
_FILLER_STRONG_RE = re.compile(
    r"(^|[、。\s\n])(" + "|".join(re.escape(f) for f in _FILLERS_STRONG)
    + r")(?=[、,\s]|$|[\u3040-\u30ff\u4e00-\u9fff])"
)
# Bare あの/その are also demonstratives ("その件"), so they count as
# fillers only when spoken standalone, i.e. followed by a pause mark.
_FILLER_WEAK_RE = re.compile(r"(^|[、。\s\n])(あの|その)(?=[、,\s])")

# Unambiguous spoken commands (safe anywhere in the text).
_COMMANDS_SAFE = [
    (re.compile(r"くうぎょう|空行"), "\n\n"),
    (re.compile(r"かいぎょう|改行"), "\n"),
    (re.compile(r"くてん"), "。"),
    (re.compile(r"とうてん"), "、"),
]

_BOUNDARY = r"(?:^|[、,。\s\n])"
_BOUNDARY_AFTER = r"(?=[、,。\s\n]|$)"
_MARU_RE = re.compile("(" + _BOUNDARY + r")まる" + _BOUNDARY_AFTER)
_TEN_RE = re.compile("(" + _BOUNDARY + r")てん" + _BOUNDARY_AFTER)
_MARU_AGGRO_RE = re.compile(r"まる(?=[\u3040-\u30ff\u4e00-\u9fff]|$)")
_TEN_AGGRO_RE = re.compile(r"(?<![\u4e00-\u9fff])てん(?=[\u3040-\u30ff\u4e00-\u9fff]|$)")

_TERMINALS = "。！？!?…」』）)\"'"
_JP_END = re.compile(r"[\u3040-\u30ff\u4e00-\u9fffー]$")


def _strip_fillers(text: str) -> str:
    # Repeat: removing one filler can expose another at the same spot.
    previous = None
    while previous != text:
        previous = text
        text = _FILLER_STRONG_RE.sub(lambda m: m.group(1), text)
        text = _FILLER_WEAK_RE.sub(lambda m: m.group(1), text)
    return text


def _apply_commands(text: str, aggressive: bool) -> str:
    for pattern, replacement in _COMMANDS_SAFE:
        text = pattern.sub(replacement, text)
    if aggressive:
        text = _MARU_AGGRO_RE.sub("。", text)
        text = _TEN_AGGRO_RE.sub("、", text)
    else:
        text = _MARU_RE.sub(lambda m: m.group(1) + "。", text)
        text = _TEN_RE.sub(lambda m: m.group(1) + "、", text)
    return text


def _normalise(text: str) -> str:
    text = text.replace("?", "？").replace("!", "！")
    # Collapse runs of the same sentence punctuation: 。。 -> 。
    text = re.sub(r"。{2,}", "。", text)
    text = re.sub(r"、{2,}", "、", text)
    text = re.sub(r"([。！？])、", r"\1", text)
    text = re.sub(r"、(?=[。！？])", "", text)
    # No punctuation straight after a newline.
    text = re.sub(r"\n[、，,]+", "\n", text)
    # Remove spaces between Japanese characters (never newlines);
    # keep single spaces elsewhere.
    text = re.sub(r"(?<=[\u3040-\u30ff\u4e00-\u9fffー])[ \t]+(?=[\u3040-\u30ff\u4e00-\u9fffー])", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Tidy each line; a line never starts with a comma.
    lines = [line.strip(" 　").lstrip("、,") for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ensure_terminal(text: str) -> str:
    if not text:
        return text
    lines = text.split("\n")
    last = lines[-1]
    if last and last[-1] not in _TERMINALS and _JP_END.search(last):
        lines[-1] = last + "。"
        text = "\n".join(lines)
    return text


def format_text(raw: str, *, remove_fillers: bool = True,
                voice_commands: bool = True,
                aggressive_commands: bool = False,
                ensure_terminal: bool = True) -> str:
    """Format one raw transcript.  Returns \"\" for empty input."""
    text = (raw or "").strip()
    if not text:
        return ""
    if voice_commands:
        text = _apply_commands(text, aggressive_commands)
    if remove_fillers:
        text = _strip_fillers(text)
    text = _normalise(text)
    if ensure_terminal:
        text = _ensure_terminal(text)
    return text
