"""Moving average colors: the chart_colors block, its settings and help rows, and the charts that use it (fixed values, no clock)."""
import json
import os
import re
import subprocess
import sys

try:
    import pytest
    _skip = pytest.skip
    _Skip = pytest.skip.Exception
except ImportError:  # the data workflow runs this file with plain python and no pytest
    class _Skip(Exception):
        pass

    def _skip(msg):
        raise _Skip(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tables  # noqa: E402

DARK = {"10": "#22c55e", "20": "#f97316", "50": "#3b82f6", "150": "#eab308", "200": "#ef4444"}
LIGHT = {"10": "#16a34a", "20": "#ea580c", "50": "#2563eb", "150": "#ca8a04", "200": "#dc2626"}


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _cfg():
    return json.loads(_read("config.json"))


def _lum(hex_color):
    h = hex_color.strip().lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _js_obj(src, name):
    m = re.search(r"const " + name + r" = (\{[^}]*\});", src)
    assert m, name
    return json.loads(m.group(1))


def test_config_block():
    block = _cfg()["chart_colors"]
    assert "_note" in block
    assert block["ma_colors"] == DARK
    assert block["ma_colors_light"] == LIGHT
    for colors in (block["ma_colors"], block["ma_colors_light"]):
        assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in colors.values())
        assert len(set(colors.values())) == 5


def test_settings_and_help_rows():
    rows = tables.settings_rows(_cfg())
    got = dict(zip(rows["setting"], rows["value"]))
    settings = _read("data", "settings.csv")
    for block, colors in (("ma_colors", DARK), ("ma_colors_light", LIGHT)):
        for n, c in colors.items():
            key = "chart_colors.%s.%s" % (block, n)
            assert got[key] == c, key
            assert "\n%s,%s\n" % (key, c) in settings, key
    assert not any(k.startswith("chart_colors._") for k in got)
    assert "chart_colors.ma_colors" not in got
    topics = dict(tables.help_rows())
    assert "Moving average colors" in topics and "chart_colors" in topics["Moving average colors"]
    assert "\nMoving average colors," in _read("data", "help.csv")


def test_readable_in_dark_and_light():
    for c in DARK.values():
        for bg in ("#0B0F17", "#121826"):  # Chart Viewer and row chart backgrounds
            assert _contrast(c, bg) >= 4.5, (c, bg)
    for c in LIGHT.values():
        assert _contrast(c, "#FFFFFF") >= 2.9, c  # both charts are white in light mode
    # The light shades are not re-mapped again by the light-mode color swap.
    light_map = re.search(r"const LIGHT_MAP = \{(.*?)\};", _read("site", "js", "desk.js"), re.S).group(1).lower()
    for c in LIGHT.values():
        assert '"%s":' % c not in light_map, c


def test_desk_row_charts_use_the_colors():
    src = _read("site", "js", "desk.js")
    assert _js_obj(src, "MA_COLORS") == DARK
    assert _js_obj(src, "MA_COLORS_LIGHT") == LIGHT
    assert 'settingVal("chart_colors." + block + "." + key)' in src
    for n in ("50", "150", "200"):
        assert re.search(r'id: "sma%s",[^}]*\bma: %s,' % (n, n), src), n
    # Line, legend, and chip all take the shared color.
    assert "color: defColor(def), lineWidth: 1" in src
    assert "color: defColor(def), value:" in src
    assert "'<i style=\"background:' + defColor(def)" in src
    assert "def.color" not in src.replace("|| def.color", "")
    assert "maColor: maColor" in src


def test_chart_viewer_uses_the_colors():
    src = _read("site", "js", "viewer.js")
    mas = re.search(r"const MAS = \[(.*?)\];", src, re.S).group(1)
    assert re.findall(r"n: (\d+)", mas) == ["10", "20", "50", "150", "200"]
    assert "#" not in mas  # no fixed colors left in the list
    assert "D.maColor(n)" in src
    assert "{ color: maColor(m.n), lineWidth: 1," in src
    assert "<i style=\"background:' + maColor(m.n) + '\"></i>MA " in src
    assert "m.color" not in src


def test_ma_color_rules():
    """Runs desk.js's maColor under node with fixed settings rows."""
    src = _read("site", "js", "desk.js")
    start = src.index("  const MA_COLORS = ")
    end = src.index("  function defColor(")
    script = (
        "let LIGHT = false; let ROWS = {};\n"
        "function settingVal(k) { return k in ROWS ? ROWS[k] : null; }\n"
        + src[start:end] +
        "const out = [];\n"
        "out.push(maColor(50), maColor(150), maColor('200'));\n"
        "LIGHT = true; out.push(maColor(150), maColor(10));\n"
        "ROWS = { 'chart_colors.ma_colors_light.150': '#111111', 'chart_colors.ma_colors_light.10': 'bad' };\n"
        "out.push(maColor(150), maColor(10));\n"
        "LIGHT = false; ROWS = { 'chart_colors.ma_colors.20': ' #abcdef ' }; out.push(maColor(20), maColor(21));\n"
        "console.log(JSON.stringify(out));\n"
    )
    try:
        proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        _skip("node is not installed: " + str(exc))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [DARK["50"], DARK["150"], DARK["200"], LIGHT["150"], LIGHT["10"],
                                       "#111111", LIGHT["10"], "#abcdef", None]


if __name__ == "__main__":
    test_config_block()
    test_settings_and_help_rows()
    test_readable_in_dark_and_light()
    test_desk_row_charts_use_the_colors()
    test_chart_viewer_uses_the_colors()
    try:
        test_ma_color_rules()
    except _Skip:
        print("node check skipped")
    print("ma colors ok")
