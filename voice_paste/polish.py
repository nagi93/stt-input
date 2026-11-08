"""Optional LLM polish for the formatted transcript.

Off by default.  When enabled, the rule-formatted text is sent to an
OpenAI-compatible chat endpoint with a strict "format only, never answer
or add content" prompt.  Any failure (timeout, HTTP error, empty reply)
returns the rule-formatted text unchanged, so dictation never blocks on
the network for long.
"""
from __future__ import annotations

import json
import os
import urllib.request

_SYSTEM = (
    "あなたは日本語の音声入力テキストの整形器です。入力は一人の発話の文字起こしです。"
    "意味を変えず、内容を加えず、質問に答えず、句読点・改行・フィラー除去だけを整えて、"
    "整形後のテキストのみを返してください。"
)


def polish(text: str, base_url: str, model: str, api_key_env: str,
           timeout: float = 5.0) -> str:
    if not text or not base_url or not model:
        return text
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": text}],
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + os.environ.get(api_key_env, "")})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            result = json.loads(r.read().decode("utf-8"))
        out = result["choices"][0]["message"]["content"].strip()
        return out or text
    except Exception:
        return text
