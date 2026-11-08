import sys
import wave
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_paste.stt_client import SttError, _text_from_result, pcm_to_wav


def test_pcm_to_wav_roundtrip():
    pcm = b"\x00\x00" * 1600  # 0.1 s of silence
    wav_bytes = pcm_to_wav(pcm)
    with wave.open(BytesIO(wav_bytes)) as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        assert wf.readframes(1600) == pcm


def test_result_ok():
    assert _text_from_result({"ok": True, "text": " こんにちは "}) == "こんにちは"


def test_result_error():
    try:
        _text_from_result({"ok": False, "error": "boom"})
    except SttError as err:
        assert "boom" in str(err)
    else:
        raise AssertionError("expected SttError")
