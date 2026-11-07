"""Nick 360 stays inside this repo, reuses stored files, and does not touch the price job."""
import os
import subprocess

try:
    import pytest
    _skip = pytest.skip
    _Skip = pytest.skip.Exception
except ImportError:
    class _Skip(Exception):
        pass

    def _skip(msg):
        raise _Skip(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def test_overview_opens_a_new_tab_and_styles_stay_isolated():
    pages = _read("site", "js", "pages.js")
    start = pages.index('<a id="nick360-open"')
    button = pages[start:start + 400]
    assert 'target="_blank"' in button
    assert 'rel="noopener noreferrer"' in button
    assert "Nick 360" in button
    assert button.count("nick360-open") == 1
    html = _read("site", "nick360", "index.html")
    assert "desk.css" not in html
    assert "nick360.css" in html
    assert "Back to Stock Box" in html
    css = _read("site", "nick360", "nick360.css")
    stripped = css
    while "/*" in stripped:
        stripped = stripped[:stripped.index("/*")] + stripped[stripped.index("*/") + 2:]
    for block in stripped.split("{"):
        sel = block.split("}")[-1].strip()
        if not sel or sel.startswith("@media"):
            continue
        assert "#n360" in sel, sel


def test_no_new_price_requests_or_job_edits():
    folder = os.path.join(ROOT, "site", "nick360")
    blob = "\n".join(_read("site", "nick360", name) for name in os.listdir(folder) if name.endswith((".js", ".html", ".css", ".md")))
    for banned in ("yfinance", "query1.finance.yahoo", "query2.finance.yahoo", "finance.yahoo.com", "ohlcv.csv.gz", "massive.com", "polygon.io"):
        assert banned not in blob.lower() if banned.islower() else banned not in blob
    assert 'csvUrl("ohlc/' in _read("site", "nick360", "app.js") or 'csvUrl("ohlc/"' in _read("site", "nick360", "app.js")
    assert "cache/ohlcv" not in blob
    # The scheduled job and its workflows are outside this change.
    for name in ("stock_desk.py", "watchdog.py", "config.json"):
        assert "nick360" not in _read(name).lower()


def test_formula_file_matches_the_engine_and_marks_gaps():
    doc = _read("site", "nick360", "FORMULAS.md")
    for phrase in (
        "Bread & Butter",
        "Leadership Five",
        "not a SPY 25",
        "listing date",
        "Power Play",
        "Quarterly sales",
        "40%",
        "prior 50",
        "not a forecast",
    ):
        assert phrase in doc
    proc = _node("tests/nick360_formulas.js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "nick360 formulas ok" in proc.stdout


def test_workspace_ui():
    env = dict(os.environ)
    proc = _node("tests/nick360_ui.mjs", env)
    out = proc.stdout + proc.stderr
    if proc.returncode == 2 or "Executable doesn't exist" in out or "Cannot find package 'playwright'" in out or "skip: playwright" in out:
        _skip("playwright is not installed")
    assert proc.returncode == 0, out
    assert "nick360 ui ok" in proc.stdout


def _node(script, env=None):
    try:
        return subprocess.run(["node", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as exc:
        _skip("node is not installed: " + str(exc))
