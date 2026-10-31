"""Light mode: the switch, the settings rows, the help row, and readable colors (fixed values, no clock)."""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tables  # noqa: E402


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _cfg():
    return json.loads(_read("config.json"))


def _vars(block_start):
    css = _read("site", "css", "desk.css")
    i = css.index(block_start)
    body = css[i:css.index("}", i)]
    return dict(re.findall(r"--([a-z0-9]+):([^;]+);", body))


def _lum(hex_color):
    h = hex_color.strip().lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_switch_and_config():
    cfg = _cfg()
    assert cfg["features"]["light_mode"] is True
    block = cfg["light_mode"]
    assert block["default_theme"] == "dark"
    assert block["match_device_option"] is True
    assert "_note" in block


def test_settings_and_help_rows():
    cfg = _cfg()
    rows = tables.settings_rows(cfg)
    got = dict(zip(rows["setting"], rows["value"]))
    assert got["feature.light_mode"] is True
    assert got["light_mode.default_theme"] == "dark"
    assert got["light_mode.match_device_option"] is True
    assert "light_mode._note" not in got
    settings = _read("data", "settings.csv")
    for line in ("feature.light_mode,True", "light_mode.default_theme,dark", "light_mode.match_device_option,True"):
        assert "\n" + line + "\n" in settings, line
    topics = [t for t, _ in tables.help_rows()]
    assert "Light mode" in topics
    assert "\nLight mode," in _read("data", "help.csv")


def test_css_uses_variables_for_both_themes():
    css = _read("site", "css", "desk.css")
    dark = _vars(":root{")
    light = _vars('html[data-theme="light"]{')
    assert set(dark) == set(light)
    # Every hex color in the stylesheet sits in one of the two variable blocks.
    head = css.index(":root{")
    tail = css.index("}", css.index('html[data-theme="light"]{')) + 1
    rest = css[:head] + css[tail:]
    assert re.findall(r"#[0-9A-Fa-f]{6}\b", rest) == []


def test_light_colors_are_readable():
    light = _vars('html[data-theme="light"]{')
    for fg in ("tx", "tx2", "mu", "up", "dn", "am", "ac", "na"):
        for bg in ("panel", "bg", "zebra", "hover"):
            ratio = _contrast(light[fg], light[bg])
            assert ratio >= 4.5, (fg, bg, round(ratio, 2))
    # Dark stays as it was.
    dark = _vars(":root{")
    assert dark["bg"] == "#0B0F17" and dark["panel"] == "#121826" and dark["tx"] == "#E6EBF5"


def test_page_scripts_swap_colors_and_offer_three_choices():
    js = _read("site", "js", "desk.js")
    assert "LIGHT_MAP" in js and "prefers-color-scheme: light" in js
    for pick in ('btn("dark", "Dark")', 'btn("light", "Light")', 'btn("auto", "Match device")'):
        assert pick in js, pick
    assert 'featureOn("feature.light_mode")' in js
    assert 'localStorage.setItem(THEME_KEY' in js
    assert '"desk-theme"' in js
    # Green and red text in the light map must read on white.
    m = dict(re.findall(r'"(#[0-9a-f]{6})": "(#[0-9A-F]{6})"', js))
    for dark_hex in ("#22c55e", "#ef4444", "#f59e0b", "#7c9cff", "#e6ebf5", "#8b96ad"):
        assert _contrast(m[dark_hex], "#FFFFFF") >= 4.5, dark_hex
    assert "\u2014" not in js


if __name__ == "__main__":
    test_switch_and_config()
    test_settings_and_help_rows()
    test_css_uses_variables_for_both_themes()
    test_light_colors_are_readable()
    test_page_scripts_swap_colors_and_offer_three_choices()
    print("light mode ok")
