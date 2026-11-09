#!/usr/bin/env python3
"""One-command update for an existing stt-input install.

    python tools/update.py          (or double-click update.bat)

Fetches the latest code from GitHub.  When this install is already up
to date it says so and touches nothing.  Otherwise it stops the
running app, aligns the tracked files with origin/main, re-runs
tools/setup_env.py (engine choices, dependencies and models are
refreshed; config.json keeps every other setting), and restarts the
app if it was running.

Alignment is a hard reset: local edits to tracked source files are
discarded, because an install is not a development checkout.
config.json, models/ and logs/ are git-ignored and always preserved.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/nagi93/stt-input.git"
MAIN_PY = APP_DIR / "main.py"


def parse_pids(text: str) -> list[int]:
    """PIDs from the stop-probe output: one integer per line, noise-free."""
    pids = []
    for line in text.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def needs_update(head: str, latest: str, dirty: bool) -> bool:
    return head != latest or dirty


def _git(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    # -c safe.directory: an install folder owned by another account
    # (e.g. created under an admin session) trips git's dubious-
    # ownership protection; trust this app's own folder for the call.
    return subprocess.run(
        ["git", "-c", f"safe.directory={APP_DIR.as_posix()}", *args],
        cwd=APP_DIR, capture_output=capture, text=capture)


def _git_out(*args: str) -> str:
    done = _git(*args, capture=True)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} が失敗しました: "
                           f"{done.stderr.strip()}")
    return done.stdout.strip()


def _ensure_origin() -> None:
    done = _git("remote", "get-url", "origin", capture=True)
    if done.returncode != 0:
        print(f"リモート origin がないため追加します: {REPO_URL}")
        _git_out("remote", "add", "origin", REPO_URL)


def app_pids() -> list[int]:
    """PIDs of the running app (python/pythonw whose cmdline is main.py).

    The query runs in PowerShell because it is the reliable way to read
    other processes' command lines on current Windows.  The path to
    match travels in an environment variable, so no quoting is needed.
    """
    script = (
        "$main = $env:STT_UPDATE_MAIN\n"
        "Get-CimInstance Win32_Process "
        "-Filter \"Name='pythonw.exe' or Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -and "
        "$_.CommandLine.Contains($main) } | "
        "ForEach-Object { $_.ProcessId }\n")
    env = dict(os.environ, STT_UPDATE_MAIN=str(MAIN_PY))
    done = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-Command", "-"],
        input=script, capture_output=True, text=True, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode != 0:
        return []
    return [pid for pid in parse_pids(done.stdout) if pid != os.getpid()]


def _stop_app(pids: list[int]) -> None:
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True)


def _restart_app() -> None:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw) if pythonw.exists() else sys.executable
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) \
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([exe, str(MAIN_PY)], cwd=APP_DIR,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags,
                     close_fds=True)


def main() -> int:
    if not (APP_DIR / ".git").is_dir():
        print("このフォルダは git 管理されていないため、自動更新できません。",
              file=sys.stderr)
        return 1
    try:
        _ensure_origin()
        print("GitHub から最新版を確認します...")
        done = _git("fetch", "origin")
        if done.returncode != 0:
            print("git fetch に失敗しました。ネットワークと GitHub への"
                  "サインインを確認してください。", file=sys.stderr)
            return 1
        head = _git_out("rev-parse", "HEAD")
        latest = _git_out("rev-parse", "origin/main")
        dirty = bool(_git_out("status", "--porcelain",
                              "--untracked-files=no"))
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 1

    if not needs_update(head, latest, dirty):
        print(f"すでに最新版です ({head[:7]})。")
        return 0
    print(f"更新します: {head[:7]} -> {latest[:7]}")

    pids = app_pids()
    if pids:
        print(f"起動中のアプリを終了します (PID: {', '.join(map(str, pids))})")
        _stop_app(pids)

    done = _git("reset", "--hard", "origin/main")
    if done.returncode != 0:
        print("コードの更新に失敗しました。", file=sys.stderr)
        return 1

    print("環境セットアップを再実行します...")
    done = subprocess.run([sys.executable,
                           str(APP_DIR / "tools" / "setup_env.py")],
                          cwd=APP_DIR)
    if done.returncode != 0:
        print("セットアップに失敗したため、アプリは終了したままです。"
              "問題を直してから run.bat で起動してください。",
              file=sys.stderr)
        return 1

    if pids:
        _restart_app()
        print("アプリを再起動しました。")
    print("更新が完了しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
