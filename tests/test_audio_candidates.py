"""Microphone endpoint ordering: 16 kHz must actually open.

Regression test for a USB audio interface failure (2026-11-09): the WASAPI
endpoint of a 44.1 kHz device cannot open at 16 kHz through PortAudio
(PaErrorCode -9997), while DirectSound/MME resample.  A WASAPI-first
preference therefore picked a microphone that could not open at all.
"""
from voice_paste.audio import _candidate_sort_key


def test_directsound_and_mme_beat_wasapi_when_rate_differs():
    ds = _candidate_sort_key("Windows DirectSound", 44100.0)
    mme = _candidate_sort_key("MME", 44100.0)
    wasapi = _candidate_sort_key("Windows WASAPI", 44100.0)
    assert ds < wasapi and mme < wasapi


def test_wasapi_first_when_native_rate_is_16k():
    wasapi = _candidate_sort_key("Windows WASAPI", 16000.0)
    ds = _candidate_sort_key("Windows DirectSound", 48000.0)
    assert wasapi < ds


def test_wdm_ks_is_last():
    ks = _candidate_sort_key("Windows WDM-KS", 44100.0)
    assert ks > _candidate_sort_key("MME", 44100.0)
    assert ks > _candidate_sort_key("Windows WASAPI", 44100.0)


def test_mic_name_key_prefers_parenthesised_part():
    from voice_paste.audio import mic_name_key
    assert mic_name_key("ライン (Yamaha AG06)") == "Yamaha AG06"
    assert mic_name_key("Microphone (USB Audio)") == "USB Audio"
    assert mic_name_key("Plain Device Name") == "Plain Device Name"
    assert mic_name_key("Empty ()") == "Empty ()"
