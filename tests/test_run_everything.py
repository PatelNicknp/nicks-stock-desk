"""Today page Run everything button opens the update workflow page and does not start a run."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_URL = "https://github.com/PatelNicknp/nicks-stock-desk/actions/workflows/update.yml"


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def _today_button_block():
    pages = _read("site", "js", "pages.js")
    start = pages.index("function renderToday")
    end = pages.index("function renderTop")
    return pages[start:end]


def test_run_everything_is_a_safe_new_tab_link_next_to_options_floor():
    block = _today_button_block()
    assert 'id="run-everything-open"' in block
    assert 'id="tito-options-floor-open"' in block
    assert block.index("tito-options-floor-open") < block.index("run-everything-open")
    start = block.index('<a id="run-everything-open"')
    button = block[start:block.index("</a>", start) + 4]
    assert 'href="' + WORKFLOW_URL + '"' in button
    assert 'target="_blank"' in button
    assert 'rel="noopener noreferrer"' in button
    assert ">Run everything</a>" in button
    assert 'background:#2b2850' in block
    assert "btnStyle" in block
    # Same pill style as Nick 360 and Options Floor: one shared style string.
    assert block.count("btnStyle") >= 3


def test_run_everything_does_not_start_a_run_or_embed_a_token():
    block = _today_button_block()
    start = block.index('<a id="run-everything-open"')
    button = block[start:block.index("</a>", start) + 4]
    banned = (
        "workflow_dispatch",
        "api.github.com",
        "actions/workflows/update.yml/dispatches",
        "Authorization",
        "Bearer ",
        "github_token",
        "GITHUB_TOKEN",
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "github_pat_",
    )
    for token in banned:
        assert token not in button, token
    # The control is a plain link. It must not fetch, post, or dispatch a workflow.
    assert "fetch(" not in block
    assert "XMLHttpRequest" not in block
    assert "workflow_dispatch" not in block
    assert "dispatchEvent" not in block
    assert block.count('<a id="run-everything-open"') == 1


def test_last_update_uses_published_desk_stamp():
    block = _today_button_block()
    assert 'id="run-everything-updated"' in block
    assert "Last update: " in block
    assert "updated_pt" in block
    assert "updates_log.csv" in block
    assert "D.formatUpdated(stamp)" in block
    assert "D.latestChecked" in block
    desk = _read("site", "js", "desk.js")
    assert "formatUpdated: formatUpdated" in desk
    assert "latestChecked: latestChecked" in desk
    # formatUpdated already turns 2026-11-10 16:05 PT into "Nov 10, 4:05 PM PT".
    fn = desk[desk.index("function formatUpdated"):desk.index("function latestChecked")]
    assert "PT" in fn
