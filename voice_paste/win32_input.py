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
import queue
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


def _declare_signatures(user32, kernel32) -> None:
    """Pointer-sized restype/argtypes for every Win32 call we make.

    ctypes defaults (int restype, int argument conversion) silently
    truncate 64-bit handles and pointers.  A truncated GlobalLock
    pointer dereferenced by c_wchar_p/memmove is an access violation
    inside _ctypes — it killed the whole app mid-dictation on
    2026-11-09, so EVERY call used here is declared, no exceptions.
    """
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

    user32.GetCursorPos.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.WindowFromPoint.argtypes = [POINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetForegroundWindow.argtypes = []
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SendInput.restype = wintypes.UINT
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT),
                                 ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                      ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                     ctypes.c_int]


_USER32 = None
_KERNEL32 = None


def _user32():
    global _USER32
    if _USER32 is None:
        _USER32 = ctypes.WinDLL("user32", use_last_error=True)
        _declare_signatures(_USER32, _kernel32())
    return _USER32


def _kernel32():
    global _KERNEL32
    if _KERNEL32 is None:
        _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return _KERNEL32


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


def window_title_at(x: int, y: int) -> str:
    """'Title [Class]' of the root window under a point (diagnostics)."""
    user32 = _user32()
    root = window_root_at(x, y)
    if not root:
        return "(no window)"
    title_buf = ctypes.create_unicode_buffer(256)
    class_buf = ctypes.create_unicode_buffer(128)
    user32.GetWindowTextW(root, title_buf, 256)
    user32.GetClassNameW(root, class_buf, 128)
    return f"{title_buf.value} [{class_buf.value}]"


# ---------------------------------------------------------------- clipboard
def _clipboard_get_text() -> str | None:
    user32, kernel32 = _user32(), _kernel32()
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
    user32, kernel32 = _user32(), _kernel32()
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
# NOTE: LRESULT and HMODULE/HHOOK are pointer-sized on 64-bit Windows.
# ctypes' default int restype silently TRUNCATES them — a truncated
# module handle makes SetWindowsHookExW fail with ERROR_MOD_NOT_FOUND
# (126) and the app then runs with no hooks at all (found live
# 2026-11-09: tray visible, side button dead).  Always set restypes.
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                              wintypes.WPARAM,
                              wintypes.LPARAM) if IS_WIN else None


class PushToTalkHook:
    """Watches XButton down/up and Esc.

    The Win32 callbacks only enqueue events; on_xbutton(button, pressed,
    x, y) and on_escape() run on a dispatcher thread (see _dispatch).
    Whether the XButton event is swallowed is the static ``suppress``
    flag — the app returns it for every path anyway.
    """

    def __init__(self, on_xbutton, on_escape, watched: set[int],
                 suppress: bool = True):
        self.on_xbutton = on_xbutton
        self.on_escape = on_escape
        self.watched = watched
        self.suppress = suppress
        self._thread: threading.Thread | None = None
        self._mouse_hook = None
        self._kbd_hook = None
        self._mouse_proc = None
        self._kbd_proc = None
        self.installed = threading.Event()
        self.install_error: str | None = None
        self.handler_error: str | None = None
        self._queue: queue.Queue = queue.Queue()

    def start(self) -> None:
        if not IS_WIN:
            raise RuntimeError("mouse hook is Windows-only")
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="ptt-hook")
        self._thread.start()
        threading.Thread(target=self._dispatch, daemon=True,
                         name="ptt-dispatch").start()

    def _dispatch(self) -> None:
        """Run the app's handlers off the hook callback.

        Low-level hook callbacks must return within ~300 ms or Windows
        silently unhooks; starting the recorder or a network stream
        from inside the callback can exceed that.  Callbacks therefore
        only enqueue (as this module's header has always promised), and
        the real work happens here.
        """
        while True:
            item = self._queue.get()
            try:
                if item[0] == "x":
                    _, button, pressed, x, y = item
                    self.on_xbutton(button, pressed, x, y)
                else:
                    self.on_escape()
            except Exception as exc:  # a bad dictation must not kill input
                self.handler_error = repr(exc)

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Both restype AND argtypes: without argtypes ctypes converts
        # the 64-bit module handle through a C int and raises
        # OverflowError before the call is even made.
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC,
                                             wintypes.HINSTANCE,
                                             wintypes.DWORD]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                          wintypes.WPARAM, wintypes.LPARAM]

        @HOOKPROC
        def mouse_proc(n_code, w_param, l_param):
            if n_code == HC_ACTION and w_param in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                button = (info.mouseData >> 16) & 0xFFFF
                if button in self.watched:
                    self._queue.put(("x", button,
                                     w_param == WM_XBUTTONDOWN,
                                     info.pt.x, info.pt.y))
                    if self.suppress:
                        return 1
            return user32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)

        @HOOKPROC
        def kbd_proc(n_code, w_param, l_param):
            if n_code == HC_ACTION and w_param == WM_KEYDOWN:
                info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if info.vkCode == VK_ESCAPE:
                    self._queue.put(("esc",))
            return user32.CallNextHookEx(self._kbd_hook, n_code, w_param, l_param)

        self._mouse_proc = mouse_proc  # keep references alive
        self._kbd_proc = kbd_proc
        try:
            module = kernel32.GetModuleHandleW(None)
            ctypes.set_last_error(0)
            self._mouse_hook = user32.SetWindowsHookExW(
                WH_MOUSE_LL, mouse_proc, module, 0)
            mouse_err = ctypes.get_last_error()
            ctypes.set_last_error(0)
            self._kbd_hook = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, kbd_proc, module, 0)
            kbd_err = ctypes.get_last_error()
            if not self._mouse_hook or not self._kbd_hook:
                self.install_error = (
                    f"SetWindowsHookExW failed (mouse={self._mouse_hook} "
                    f"err={mouse_err}, kbd={self._kbd_hook} err={kbd_err})")
        except Exception as exc:  # never leave main() waiting blind
            self.install_error = f"hook install raised: {exc!r}"
        finally:
            self.installed.set()
        if self.install_error:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
