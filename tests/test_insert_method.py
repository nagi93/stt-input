"""Route resolution for text insertion (pure logic, runs anywhere)."""
from voice_paste.win32_input import choose_insert_method


def test_forced_methods_pass_through():
    assert choose_insert_method("type", "chrome.exe",
                                "Chrome_RenderWidgetHostHWND") == "type"
    assert choose_insert_method("paste", "notepad.exe", "") == "paste"


def test_auto_browser_gets_wmchar():
    assert choose_insert_method(
        "auto", "chrome.exe", "Chrome_RenderWidgetHostHWND") == "wmchar"
    assert choose_insert_method(
        "auto", "msedge.exe", "Chrome_RenderWidgetHostHWND") == "wmchar"
    assert choose_insert_method(
        "auto", "firefox.exe", "MozillaWindowClass") == "wmchar"


def test_auto_electron_gets_wmchar_via_renderer_class():
    # VS Code / Discord are not in BROWSER_PROCESSES, but their content
    # child is a RenderWidgetHost and garbles the same way.
    assert choose_insert_method(
        "auto", "code.exe", "Chrome_RenderWidgetHostHWND") == "wmchar"


def test_auto_native_apps_get_typing():
    assert choose_insert_method("auto", "notepad.exe", "") == "type"
    assert choose_insert_method("auto", "winword.exe", "") == "type"
    # Browser window but no child window under the point: typing is the
    # safe fallback rather than posting into the void.
    assert choose_insert_method("auto", "chrome.exe", "") == "type"


def test_wmchar_forced():
    assert choose_insert_method(
        "wmchar", "notepad.exe", "RichEditD2DPT") == "wmchar"
    assert choose_insert_method("wmchar", "notepad.exe", "") == "type"


def test_unknown_method_behaves_like_auto():
    assert choose_insert_method(
        "bogus", "chrome.exe", "Chrome_RenderWidgetHostHWND") == "wmchar"
    assert choose_insert_method("bogus", "notepad.exe", "") == "type"
