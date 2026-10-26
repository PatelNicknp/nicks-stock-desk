"""Keep the update on New York market time and make up missed runs. Standard library only.

Never calls Yahoo. Two commands:

    python watchdog.py check     # watchdog workflow: dispatch one make-up if a slot was missed
    python watchdog.py guard     # first step of the update job

Intended slots are New York time (America/New_York), Monday to Friday:
hourly at 10:15, 11:15, ... 17:15 and the full run at 18:30. GitHub cron is UTC only,
so update.yml lists the UTC times for both EDT and EST. Twice as many crons fire, and the
guard lets through only the ones that land on an intended New York slot. The others stop
after a few seconds, before any data step. One run per intended slot, so Yahoo traffic is
the same in summer and winter.

guard (scheduled and watchdog runs only; manual runs are never skipped):
1. Scheduled run: work out which cron time fired (from the cron string and the run's
   creation time), convert it to New York time, and skip unless it is an intended slot.
   The mode (hourly or full) comes from the slot.
2. Skip when another real run already started for the same slot. This collapses a late
   cron and a watchdog make-up into one run. If the run list cannot be read, run.

check (switch features.self_heal_schedule): do nothing while an update is queued or
running, or when the latest intended slot already ran. Dispatch exactly one update when
that slot is 20 minutes to 3 hours past and the last real update started over 75 minutes ago.
A run whose data step was skipped by the guard does not count as a run. A failed run does
count, so it is never retried. A cancelled run does not count.
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
NY = ZoneInfo("America/New_York")
WORKFLOW_FILE = "update.yml"
DATA_STEP = "Update the desk"
# Intended slots in New York time, Monday to Friday. Same as the old UTC crons during EDT.
HOURLY_NY = [(h, 15) for h in range(10, 18)]   # 10:15 .. 17:15
FULL_NY = (18, 30)
GRACE_MIN = 20
OVERDUE_MIN = 75
MAX_LATE_MIN = 180
ACTIVE = {"queued", "in_progress", "waiting", "requested", "pending"}
NOT_A_RUN = {"cancelled", "skipped", "startup_failure", "stale"}


def parse_time(s):
    if not s:
        return None
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def fmt(t):
    return t.astimezone(NY).strftime("%a %H:%M ET")


def slots_for_day(day):
    """Intended (utc_time, mode) slots for one New York calendar date. Empty on weekends."""
    if day.weekday() >= 5:
        return []
    out = []
    for h, m in HOURLY_NY:
        out.append((dt.datetime(day.year, day.month, day.day, h, m, tzinfo=NY).astimezone(UTC), "hourly"))
    out.append((dt.datetime(day.year, day.month, day.day, FULL_NY[0], FULL_NY[1], tzinfo=NY).astimezone(UTC), "full"))
    return out


def last_slot(at):
    """Most recent intended slot at or before `at` (aware datetime), looking back up to a week."""
    ny_day = at.astimezone(NY).date()
    for back in range(0, 8):
        due = [s for s in slots_for_day(ny_day - dt.timedelta(days=back)) if s[0] <= at]
        if due:
            return due[-1]
    return None, None


def slot_mode_at(t):
    """'hourly' or 'full' when the UTC time t is exactly an intended New York slot, else None."""
    for when, mode in slots_for_day(t.astimezone(NY).date()):
        if when == t:
            return mode
    return None


# ---------------------------------------------------------------- cron
def _field(spec, lo, hi):
    if spec == "*":
        return set(range(lo, hi + 1))
    out = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def cron_fire_time(cron, created):
    """Latest UTC time <= created that matches a simple 'M H * * DOW' cron. None if unknown."""
    try:
        minute, hour, dom, mon, dow = cron.split()
        if dom != "*" or mon != "*":
            return None
        minutes = _field(minute, 0, 59)
        hours = _field(hour, 0, 23)
        days = {d % 7 for d in _field(dow, 0, 7)}  # cron: 0 or 7 = Sunday
    except Exception:
        return None
    t = created.replace(second=0, microsecond=0)
    for _ in range(0, 60 * 24 * 7):
        cron_dow = (t.weekday() + 1) % 7  # Python Monday=0 -> cron Monday=1
        if t.minute in minutes and t.hour in hours and cron_dow in days:
            return t
        t -= dt.timedelta(minutes=1)
    return None


def schedule_gate(cron, created):
    """For a scheduled run: (run, mode, why). Skips crons that are not an intended NY slot."""
    fired = cron_fire_time(cron or "", created)
    if fired is None:
        return True, ("full" if str(cron).startswith("30 ") else "hourly"), "could not read the cron, run as usual"
    mode = slot_mode_at(fired)
    if mode is None:
        return False, None, "cron %s fired for %s, which is not a New York slot" % (cron, fmt(fired))
    return True, mode, "cron %s is the %s %s slot" % (cron, fmt(fired), mode)


# ---------------------------------------------------------------- decisions
def run_start(run):
    return parse_time(run.get("run_started_at") or run.get("created_at"))


def counts_as_run(run, did_work=None):
    """A run that happened or is happening. Cancelled runs and guard-skipped runs do not count."""
    if run.get("status") in ACTIVE:
        return True
    if run.get("conclusion") in NOT_A_RUN:
        return False
    if did_work is not None and not did_work(run):
        return False
    return True


def decide(now, runs, enabled=True, did_work=None):
    """Return (action, reason, mode). action is 'dispatch' or 'none'."""
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
        return "none", "last expected slot %s is %.0f min old, too old to make up" % (fmt(slot), late), None
    latest = None
    for r in sorted(runs, key=lambda r: run_start(r) or dt.datetime.min.replace(tzinfo=UTC), reverse=True):
        if run_start(r) is not None and counts_as_run(r, did_work):
            latest = run_start(r)
            break
    if latest is not None and latest >= slot:
        return "none", "slot %s already ran (last start %s)" % (fmt(slot), fmt(latest)), None
    if latest is not None and (now - latest).total_seconds() / 60.0 < OVERDUE_MIN:
        return "none", "last start %s is under %d min ago" % (fmt(latest), OVERDUE_MIN), None
    return "dispatch", "missed slot %s (%s); last start %s" % (
        fmt(slot), mode, fmt(latest) if latest else "none"), mode


def duplicate(me, runs, did_work=None):
    """Return (skip, reason): skip when another real run already started for the same slot."""
    created = parse_time(me.get("created_at"))
    if created is None:
        return False, "no start time, run as usual"
    slot, _ = last_slot(created)
    if slot is None:
        return False, "no expected slot, run as usual"
    for r in runs:
        if r.get("id") == me.get("id"):
            continue
        c = parse_time(r.get("created_at"))
        if c is None:
            continue
        if not (slot <= c < created or (c == created and r.get("id", 0) < me.get("id", 0))):
            continue
        if counts_as_run(r, did_work):
            return True, "run %s already covers slot %s" % (r.get("id"), fmt(slot))
    return False, "first run for slot %s" % fmt(slot)


# Kept for callers and tests from the first version.
def guard(me, runs, enabled=True, did_work=None):
    return duplicate(me, runs, did_work)


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


def fetch_runs(n=50):
    return _api("GET", "/actions/workflows/%s/runs?per_page=%d" % (WORKFLOW_FILE, n)).get("workflow_runs", [])


_WORK = {}


def api_did_work(run):
    """True unless the run finished and its data step was skipped by the guard. Looked up lazily."""
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return True
    rid = run.get("id")
    if rid not in _WORK:
        try:
            jobs = _api("GET", "/actions/runs/%s/jobs" % rid).get("jobs", [])
            steps = [s for j in jobs for s in (j.get("steps") or []) if s.get("name") == DATA_STEP]
            _WORK[rid] = not steps or any(s.get("conclusion") != "skipped" for s in steps)
        except Exception:
            _WORK[rid] = True
    return _WORK[rid]


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


def run_guard(env, fetch=None):
    """Return (skip, mode). Scheduled runs pass the New York check, then the duplicate check."""
    fetch = fetch or fetch_runs
    event = env.get("EVENT_NAME", "")
    now = dt.datetime.now(UTC).replace(microsecond=0)
    runs, err = None, None
    try:
        runs = fetch()
    except Exception as e:
        err = e
    me = None
    if runs is not None:
        me = next((r for r in runs if str(r.get("id")) == str(env.get("GITHUB_RUN_ID"))), None)
    if me is None:
        me = {"id": int(env.get("GITHUB_RUN_ID", "0") or 0), "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    mode = ""
    if event == "schedule":
        go, mode, why = schedule_gate(env.get("SCHEDULE", ""), parse_time(me.get("created_at")) or now)
        print("guard (New York time):", "RUN" if go else "SKIP", "-", why)
        if not go:
            return True, ""
    if runs is None:  # fail open: behave like before
        print("guard (duplicate slot): RUN - could not read runs (%s), run as usual" % err)
        return False, mode or ""
    skip, why = duplicate(me, runs, api_did_work)
    print("guard (duplicate slot):", "SKIP" if skip else "RUN", "-", why)
    return skip, mode or ""


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "guard":
        skip, mode = run_guard(os.environ)
        _out("skip", "true" if skip else "false")
        _out("mode", mode)
        return 0
    dry = "--dry-run" in argv or os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    enabled = switch_on()
    now = dt.datetime.now(UTC)
    runs = fetch_runs() if enabled else []
    action, why, mode = decide(now, runs, enabled, api_did_work)
    print("watchdog decision:", action.upper(), "-", why, "(dry run)" if dry else "")
    _out("action", action)
    if action == "dispatch" and not dry:
        _api("POST", "/actions/workflows/%s/dispatches" % WORKFLOW_FILE,
             {"ref": "main", "inputs": {"mode": mode, "reason": "watchdog"}})
        print("dispatched one %s update" % mode)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
