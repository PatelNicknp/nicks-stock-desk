"""Self-heal for the update schedule. Standard library only. Never calls Yahoo.

GitHub sometimes skips or delays scheduled (cron) runs. The watchdog workflow runs
this script a few times an hour during the update window:

    python watchdog.py check     # decide, and dispatch one make-up run if a slot was missed
    python watchdog.py guard     # first step of the update job: skip a duplicate run

Rules (only a missed run is made up, never an extra one):
- The switch features.self_heal_schedule in config.json must be on.
- If any update run is queued, waiting, or in progress, do nothing.
- Find the most recent expected slot (same times as the update crons) that is at
  least GRACE_MIN old and at most MAX_LATE_MIN old.
- If an update run already started at or after that slot, do nothing.
- If the last update run started less than OVERDUE_MIN ago, do nothing.
- Otherwise dispatch one update, in the same mode the missed slot would have used
  (hourly or full), tagged reason=watchdog.

The guard makes a cron run and a watchdog run that land together collapse into one:
a scheduled or watchdog run steps aside when another real run already started for
the same slot before it.
"""
import datetime as dt
import json
import os
import sys
import urllib.request

UTC = dt.timezone.utc
WORKFLOW_FILE = "update.yml"
WORKFLOW_NAME = "Update Nick's Stock Desk"
# Same as the crons in .github/workflows/update.yml (UTC, Monday to Friday).
HOURLY_HOURS = range(14, 22)   # "15 14-21 * * 1-5"
HOURLY_MINUTE = 15
FULL_SLOT = (22, 30)           # "30 22 * * 1-5"
GRACE_MIN = 20       # give a late cron this long before calling the slot missed
OVERDUE_MIN = 75     # and the last start must be at least this old
MAX_LATE_MIN = 180   # do not make up a slot older than this
ACTIVE = {"queued", "in_progress", "waiting", "requested", "pending"}
NOT_A_RUN = {"cancelled", "skipped", "startup_failure", "stale"}


def parse_time(s):
    if not s:
        return None
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def slots_for_day(day):
    """Expected (time, mode) slots for one UTC date. Empty on Saturday and Sunday."""
    if day.weekday() >= 5:
        return []
    out = []
    for h in HOURLY_HOURS:
        out.append((dt.datetime(day.year, day.month, day.day, h, HOURLY_MINUTE, tzinfo=UTC), "hourly"))
    out.append((dt.datetime(day.year, day.month, day.day, FULL_SLOT[0], FULL_SLOT[1], tzinfo=UTC), "full"))
    return out


def last_slot(at):
    """Most recent expected slot at or before `at`, looking back up to a week."""
    for back in range(0, 8):
        day = (at - dt.timedelta(days=back)).date()
        due = [s for s in slots_for_day(day) if s[0] <= at]
        if due:
            return due[-1]
    return None, None


def run_start(run):
    return parse_time(run.get("run_started_at") or run.get("created_at"))


def counts_as_run(run):
    """A run that actually happened or is happening. Cancelled or skipped runs do not count."""
    if run.get("status") in ACTIVE:
        return True
    if run.get("conclusion") in NOT_A_RUN:
        return False
    return True


def decide(now, runs, enabled=True):
    """Return (action, reason, mode). action is 'dispatch' or 'none'. runs: GitHub run dicts."""
    if not enabled:
        return "none", "switch self_heal_schedule is off", None
    active = [r for r in runs if r.get("status") in ACTIVE]
    if active:
        return "none", "an update run is already %s (run %s)" % (active[0].get("status"), active[0].get("id")), None
    slot, mode = last_slot(now - dt.timedelta(minutes=GRACE_MIN))
    if slot is None:
        return "none", "no expected slot", None
    late = (now - slot).total_seconds() / 60.0
    if late > MAX_LATE_MIN:
        return "none", "last expected slot %s is %.0f min old, too old to make up" % (slot.strftime("%a %H:%M UTC"), late), None
    real = [r for r in runs if counts_as_run(r) and run_start(r) is not None]
    starts = sorted((run_start(r) for r in real), reverse=True)
    latest = starts[0] if starts else None
    if latest is not None and latest >= slot:
        return "none", "slot %s already ran (last start %s)" % (slot.strftime("%a %H:%M UTC"), latest.strftime("%a %H:%M UTC")), None
    if latest is not None and (now - latest).total_seconds() / 60.0 < OVERDUE_MIN:
        return "none", "last start %s is under %d min ago" % (latest.strftime("%a %H:%M UTC"), OVERDUE_MIN), None
    return "dispatch", "missed slot %s (%s); last start %s" % (
        slot.strftime("%a %H:%M UTC"), mode, latest.strftime("%a %H:%M UTC") if latest else "none"), mode


def guard(me, runs, enabled=True):
    """Return (skip, reason) for the update run `me`. Only scheduled and watchdog runs step aside."""
    if not enabled:
        return False, "switch off, run as usual"
    created = parse_time(me.get("created_at"))
    if created is None:
        return False, "no start time, run as usual"
    slot, _ = last_slot(created)
    if slot is None:
        return False, "no expected slot, run as usual"
    for r in runs:
        if r.get("id") == me.get("id") or not counts_as_run(r):
            continue
        c = parse_time(r.get("created_at"))
        if c is None:
            continue
        if slot <= c < created or (c == created and r.get("id", 0) < me.get("id", 0)):
            return True, "run %s already covers slot %s" % (r.get("id"), slot.strftime("%a %H:%M UTC"))
    return False, "first run for slot %s" % slot.strftime("%a %H:%M UTC")


# ---------------------------------------------------------------- GitHub API
def _api(method, path, body=None):
    repo = os.environ["GITHUB_REPOSITORY"]
    url = "https://api.github.com/repos/%s%s" % (repo, path)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def fetch_runs(n=30):
    got = _api("GET", "/actions/workflows/%s/runs?per_page=%d" % (WORKFLOW_FILE, n))
    return got.get("workflow_runs", [])


def switch_on(path="config.json"):
    try:
        with open(path) as f:
            cfg = json.load(f)
    except Exception:
        return True
    return bool((cfg.get("features") or {}).get("self_heal_schedule", True))


def _out(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write("%s=%s\n" % (key, value))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "check"
    dry = "--dry-run" in argv or os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    enabled = switch_on()
    if cmd == "guard":
        try:
            runs = fetch_runs()
            me = next((r for r in runs if str(r.get("id")) == os.environ.get("GITHUB_RUN_ID")), None)
            if me is None:
                me = {"id": int(os.environ.get("GITHUB_RUN_ID", "0")), "created_at": dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
            skip, why = guard(me, runs, enabled)
        except Exception as e:  # fail open: behave exactly like before the watchdog existed
            skip, why = False, "guard could not read runs (%s), run as usual" % e
        print("guard:", "SKIP" if skip else "RUN", "-", why)
        _out("skip", "true" if skip else "false")
        return 0
    now = dt.datetime.now(UTC)
    runs = fetch_runs() if enabled else []
    action, why, mode = decide(now, runs, enabled)
    print("watchdog decision:", action.upper(), "-", why, "(dry run)" if dry else "")
    _out("action", action)
    if action == "dispatch" and not dry:
        _api("POST", "/actions/workflows/%s/dispatches" % WORKFLOW_FILE,
             {"ref": "main", "inputs": {"mode": mode, "reason": "watchdog"}})
        print("dispatched one %s update" % mode)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
