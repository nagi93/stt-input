import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_paste.local_stt import LocalAgreement


def test_committed_grows_with_agreement():
    a = LocalAgreement()
    committed, pending = a.update("明日の会議は")
    assert committed == "" and pending == "明日の会議は"
    committed, pending = a.update("明日の会議は三時")
    assert committed == "明日の会議は" and pending == "三時"
    committed, pending = a.update("明日の会議は三時からです")
    assert committed == "明日の会議は三時" and pending == "からです"


def test_committed_never_shrinks():
    a = LocalAgreement()
    a.update("今日は晴れです")
    a.update("今日は晴れです明日も")
    committed, pending = a.update("今日は雨です")  # hypothesis flips
    # Once committed, text is not taken back (the final read corrects it).
    assert committed == "今日は晴れです"
    assert pending == "今日は雨です"


def test_reset():
    a = LocalAgreement()
    a.update("テストです")
    a.reset()
    committed, pending = a.update("次です")
    assert committed == "" and pending == "次です"
