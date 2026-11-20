"""MarketSurge-style Chart Viewer: config switches, settings and help, wiring, and the node and browser checks."""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tables  # noqa: E402

NEW_KEYS = ["comp_chip", "comp_chip_green_min", "ms_look", "ma_21", "volume_avg_line", "patterns", "pattern_history",
            "pattern_labels", "pivot_lines", "buy_zone", "pattern_caption", "scanner_pivots"]


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _cfg():
    return json.loads(_read("config.json"))


def test_every_new_piece_has_its_own_switch_in_config():
    cfg = _cfg()
    cv = cfg["chart_viewer"]
    for k in NEW_KEYS:
        assert k in cv, k
    assert cv["comp_chip"] is True and cv["comp_chip_green_min"] == 80
    assert cv["ms_look"] is True and cv["ma_21"] is False and cv["volume_avg_line"] is True
    for k in ("patterns", "pattern_history", "pattern_labels", "pivot_lines", "buy_zone", "pattern_caption", "scanner_pivots"):
        assert cv[k] is True, k
    assert cfg["features"]["composite_rating"] is True and cfg["features"]["base_patterns"] is True
    for k in NEW_KEYS:
        assert k in cv["_note"], k
    assert "side panel" in cv["_note"]


def test_settings_help_and_published_files_carry_the_new_options():
    cfg = _cfg()
    rows = tables.settings_rows(cfg)
    got = dict(zip(rows["setting"], rows["value"]))
    for k in NEW_KEYS:
        assert got["chart_viewer." + k] == cfg["chart_viewer"][k], k
    for k in ("w_eps", "w_rs", "w_high", "w_sales", "w_margin", "min_parts"):
        assert got["composite." + k] == cfg["composite"][k], k
    for k, v in cfg["base_patterns"].items():
        if not k.startswith("_"):
            assert got["base_patterns." + k] == v, k
    settings = _read("data", "settings.csv")
    for key in got:
        if key.startswith(("chart_viewer.", "composite.", "base_patterns.")) or key in ("feature.composite_rating", "feature.base_patterns"):
            assert "\n" + key + "," in settings, key
    helps = dict(tables.help_rows())
    for topic in ("Chart Viewer Composite chip", "Chart Viewer base patterns", "Chart Viewer MarketSurge look"):
        assert topic in helps and "\n" + topic + "," in _read("data", "help.csv"), topic
        assert "\u2014" not in helps[topic]
    assert "Comp 91" in helps["Chart Viewer Composite chip"] and "chart_viewer.comp_chip" in helps["Chart Viewer Composite chip"]
    for phrase in ("MarketSurge's own rules are private", "5%", "10 cents", "features.base_patterns"):
        assert phrase in helps["Chart Viewer base patterns"], phrase
    for k in NEW_KEYS:
        if k != "ma_21":
            assert k in helps["Chart Viewer settings"] or k in helps["Chart Viewer MarketSurge look"], k
    assert "ma_21" in helps["Chart Viewer MarketSurge look"]


def test_description_box_mentions_comp_patterns_and_look():
    pages = _read("site", "js", "pages.js")
    assert 'D.viewerOn("comp_chip")) text += " " + COMP_BADGE_DESC' in pages
    assert 'D.viewerOn("patterns") && D.featureOn("feature.base_patterns")) text += " " + PATTERN_DESC' in pages
    assert 'D.viewerOn("ms_look")) text += " " + MS_LOOK_DESC' in pages
    assert "The Comp chip, right after the EPS chip" in pages and "MarketSurge's own are private" in pages


def test_viewer_wiring_has_no_side_panel_and_no_new_requests():
    js = _read("site", "js", "viewer.js")
    assert "const chips = rsBadge + epsBadge + compBadge + " in js
    assert 'on("comp_chip") ? \'<span class="cvchip compchip" id="cvcomp" hidden></span>\'' in js
    assert 'compChip(it.comp, cfgNum("comp_chip_green_min", 80))' in js
    assert "comp: compOf(s.composite_rating)" in js
    for key in ("ms_look", "volume_avg_line", "patterns", "pattern_history", "pattern_labels", "pivot_lines", "buy_zone", "pattern_caption", "scanner_pivots"):
        assert 'on("%s")' % key in js, key
    assert 'optionalFiles: ["base_patterns.csv"]' in js
    assert "price.attachPrimitive(baseOverlay(" in js
    assert "fetch(" not in js and "yahoo" not in js.lower() and "massive" not in js.lower()
    # No side panel: nothing is added next to the chart besides the existing Why box.
    assert "sidepanel" not in js.lower() and "side-panel" not in js.lower()
    css = _read("site", "css", "desk.css")
    assert ".cvchip.compchip{" in css and ".cvchip.compchip.hot{color:var(--up);border-color:var(--up)}" in css
    assert ".cvchip[hidden]{display:none}" in css


def test_no_raw_price_files_are_added_by_this_feature():
    out = subprocess.run(["git", "ls-files", "-o", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert not [f for f in out if re.search(r"massive|raw|\.zip$|\.gz$", f, re.I)]
    code = _read("base_patterns.py") + _read("composite.py")
    assert "massive" not in code.lower() and "requests" not in code and "urlopen" not in code and "yfinance" not in code


def _node(script, ok_text, env=None, timeout=300):
    try:
        proc = subprocess.run(["node", os.path.join("tests", script)], cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError:
        print("node is not installed, " + script + " skipped")
        return
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert ok_text in proc.stdout


def test_chip_shape_and_caption_rules_in_node():
    _node("marketsurge_check.js", "marketsurge check ok")


def test_marketsurge_look_in_a_real_browser():
    env = dict(os.environ)
    for root in ("/tmp/pw/node_modules/playwright", os.environ.get("PLAYWRIGHT_ROOT", "")):
        if root and os.path.isdir(root):
            env["PLAYWRIGHT_ROOT"] = root
            break
    probe = subprocess.run(["node", "-e", "import('playwright').then(()=>process.exit(0),()=>process.exit(1))"], cwd=ROOT, capture_output=True)
    if probe.returncode != 0 and "PLAYWRIGHT_ROOT" not in env:
        print("playwright is not installed, browser check skipped")
        return
    _node("marketsurge_view.mjs", "marketsurge view ok", env=env)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("marketsurge chart tests ok")
