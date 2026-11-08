import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_paste.formatter import format_text


def test_empty():
    assert format_text("") == ""
    assert format_text("   ") == ""


def test_terminal_period_added():
    assert format_text("明日の会議は三時からです") == "明日の会議は三時からです。"


def test_terminal_kept():
    assert format_text("本当ですか？") == "本当ですか？"
    assert format_text("すごい!") == "すごい！"


def test_fillers_removed():
    assert format_text("えーと明日の会議は三時からです") == "明日の会議は三時からです。"
    assert format_text("あのー、その件は終わりました") == "その件は終わりました。"


def test_safe_commands():
    assert format_text("結論ですくてん理由は後です") == "結論です。理由は後です。"
    assert format_text("りんごとうてんみかん") == "りんご、みかん。"
    assert format_text("一行目かいぎょう二行目") == "一行目\n二行目。"


def test_isolated_maru_ten():
    assert format_text("今日は晴れです、まる") == "今日は晴れです。"
    assert format_text("りんご、てん、みかん") == "りんご、みかん。"


def test_maru_inside_sentence_not_converted_by_default():
    # まる followed directly by more text is left alone in safe mode.
    out = format_text("今日は晴れですまる明日も晴れです")
    assert out == "今日は晴れですまる明日も晴れです。"


def test_aggressive_maru():
    out = format_text("今日は晴れですまる明日も晴れですまる", aggressive_commands=True)
    assert out == "今日は晴れです。明日も晴れです。"


def test_duplicate_punctuation_collapsed():
    assert format_text("終わりました。。") == "終わりました。"


def test_commands_can_be_disabled():
    assert format_text("結論ですくてん", voice_commands=False) == "結論ですくてん。"
