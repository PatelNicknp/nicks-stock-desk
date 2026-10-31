"""Phone width must not scroll sideways, and every page is a home-screen app."""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")


def test_pages_advertise_a_home_screen_app():
    htmls = [n for n in os.listdir(SITE) if n.endswith(".html")]
    assert len(htmls) == 53
    for name in htmls:
        text = open(os.path.join(SITE, name), encoding="utf-8").read()
        assert "viewport-fit=cover" in text, name
        assert 'name="apple-mobile-web-app-capable" content="yes"' in text, name
        assert 'name="apple-mobile-web-app-title" content="Nick\'s Stock Desk"' in text, name
        assert 'rel="apple-touch-icon"' in text, name
    assert os.path.exists(os.path.join(SITE, "apple-touch-icon.png"))
    assert "Nick's Stock Desk" in open(os.path.join(SITE, "manifest.webmanifest"), encoding="utf-8").read()


def test_phone_pages_have_no_horizontal_overflow():
    script = os.path.join(ROOT, "tests", "mobile_overflow.js")
    try:
        proc = subprocess.run(
            ["node", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except FileNotFoundError as exc:
        pytest.skip("node is not installed: " + str(exc))
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 2:
        pytest.skip(out.strip() or "playwright is not installed")
    assert proc.returncode == 0, out


if __name__ == "__main__":
    test_pages_advertise_a_home_screen_app()
    try:
        test_phone_pages_have_no_horizontal_overflow()
    except pytest.skip.Exception:
        print("overflow check skipped")
    print("mobile ok")
