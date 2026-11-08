"""Windows input plumbing (ctypes only, no pywin32).

* Low-level mouse hook (WH_MOUSE_LL) watching the XButtons (side buttons)
  for push-to-talk.  The hook runs on a dedicated thread with its own
  message pump; callbacks must return fast, so they only enqueue events.
* Low-level keyboard hook for Esc (cancel while recording).
* Text injection: set the clipboard (CF_UNICODETEXT) and send Ctrl+V with
  SendInput, then restore the previous clipboard contents.
* Focus helper: click the window under the cursor so the pasted text lands
  where the user is pointing, as requested ("release over the target").
"""
from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes

IS_WIN = sys.platform == "win32"

WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_KEYDOWN = 0x0100
VK_ESCAPE = 0x1B
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002
HC_ACTION = 0

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_CONTROL = 0x11
VK_V = 0x56

GA_ROOT = 2


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _user32():
    return ctypes.windll.user32


def get_cursor_pos() -> tuple[int, int]:
    pt = POINT()
    _user32().GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def window_root_at(x: int, y: int) -> int:
    user32 = _user32()
    hwnd = user32.WindowFromPoint(POINT(x, y))
    if hwnd:
        root = user32.GetAncestor(hwnd, GA_ROOT)
        if root:
            return root
    return hwnd or 0


# ---------------------------------------------------------------- clipboard
def _clipboard_get_text() -> str | None:
    user32, kernel32 = _user32(), ctypes.windll.kernel32
    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.c_wchar_p(ptr).value
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _clipboard_set_text(text: str) -> bool:
    user32, kernel32 = _user32(), ctypes.windll.kernel32
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        return bool(user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------- injection
def _send_inputs(inputs: list[INPUT]) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    _user32().SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _key(vk: int, up: bool = False) -> INPUT:
    return INPUT(INPUT_KEYBOARD, _INPUTUNION(
        ki=_KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, None)))


def _mouse(flags: int) -> INPUT:
    return INPUT(INPUT_MOUSE, _INPUTUNION(
        mi=_MOUSEINPUT(0, 0, 0, flags, 0, None)))


def click_at_cursor() -> None:
    """Left-click at the current cursor position (focuses the target)."""
    _send_inputs([_mouse(MOUSEEVENTF_LEFTDOWN)])
    time.sleep(0.03)
    _send_inputs([_mouse(MOUSEEVENTF_LEFTUP)])


def paste_text(text: str, restore_clipboard: bool = True,
               settle_seconds: float = 0.35) -> None:
    """Paste ``text`` into the focused control via the clipboard + Ctrl+V."""
    previous = _clipboard_get_text() if restore_clipboard else None
    if not _clipboard_set_text(text):
        # Clipboard busy: fall back to typing the text char by char.
        _type_unicode(text)
        return
    time.sleep(0.02)
    _send_inputs([_key(VK_CONTROL), _key(VK_V),
                  _key(VK_V, up=True), _key(VK_CONTROL, up=True)])
    if restore_clipboard:
        time.sleep(settle_seconds)  # let the target app read the clipboard
        if previous is not None:
            _clipboard_set_text(previous)


def _type_unicode(text: str) -> None:
    for ch in text:
        code = ord(ch)
        down = INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=_KEYBDINPUT(
            0, code, KEYEVENTF_UNICODE, 0, None)))
        up = INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=_KEYBDINPUT(
            0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)))
        _send_inputs([down, up])


def focus_and_paste(text: str, click_to_focus: bool = True,
                    restore_clipboard: bool = True) -> None:
    """Click the control under the cursor (if asked), then paste."""
    if click_to_focus:
        x, y = get_cursor_pos()
        root = window_root_at(x, y)
        user32 = _user32()
        if root and root != user32.GetForegroundWindow():
            try:
                user32.SetForegroundWindow(root)
            except Exception:
                pass
        click_at_cursor()
        time.sleep(0.06)
    paste_text(text, restore_clipboard=restore_clipboard)


# ------------------------------------------------------------------- hooks
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM,
                              wintypes.LPARAM) if IS_WIN else None


class PushToTalkHook:
    """Watches XButton down/up and Esc.  Callbacks receive plain events:

    on_xbutton(button_id, pressed, x, y) -> return True to swallow the event
    on_escape() -> None
    """

    def __init__(self, on_xbutton, on_escape, watched: set[int]):
        self.on_xbutton = on_xbutton
        self.on_escape = on_escape
        self.watched = watched
        self._thread: threading.Thread | None = None
        self._mouse_hook = None
        self._kbd_hook = None
        self._mouse_proc = None
        self._kbd_proc = None

    def start(self) -> None:
        if not IS_WIN:
            raise RuntimeError("mouse hook is Windows-only")
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="ptt-hook")
        self._thread.start()

    def _run(self) -> None:
        user32 = _user32()
        kernel32 = ctypes.windll.kernel32

        @HOOKPROC
        def mouse_proc(n_code, w_param, l_param):
            swallow = False
            if n_code == HC_ACTION and w_param in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                button = (info.mouseData >> 16) & 0xFFFF
                if button in self.watched:
                    swallow = bool(self.on_xbutton(
                        button, w_param == WM_XBUTTONDOWN, info.pt.x, info.pt.y))
            if swallow:
                return 1
            return user32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)

        @HOOKPROC
        def kbd_proc(n_code, w_param, l_param):
            if n_code == HC_ACTION and w_param == WM_KEYDOWN:
                info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if info.vkCode == VK_ESCAPE:
                    self.on_escape()
            return user32.CallNextHookEx(self._kbd_hook, n_code, w_param, l_param)

        self._mouse_proc = mouse_proc  # keep references alive
        self._kbd_proc = kbd_proc
        module = kernel32.GetModuleHandleW(None)
        self._mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, module, 0)
        self._kbd_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, kbd_proc, module, 0)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
