"""Offline checks for the update keeper: next-slot and sleep math, the 'already ran' check,
single-keeper rules, the switch, and the run loop with a fake clock. No network, no real clock.

2026-11-02 is a Monday (EST, UTC-5). DST ended Sun 2026-11-01; 2027 DST starts Sun 2027-03-14.
"""
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watchdog as w
import tables

UTC = dt.timezone.utc


def T(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def run(i, start, status="completed", conclusion="success", worked=True):
    stamp = T(start).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": i, "status": status, "conclusion": conclusion,
            "created_at": stamp, "run_started_at": stamp, "_worked": worked}


def did_work(r):
    return r.get("_worked", True)


def nc(now, lag=10):
    when, slot, mode = w.next_check(T(now), lag)
    return when.strftime("%Y-%m-%d %H:%M"), slot.strftime("%Y-%m-%d %H:%M"), mode


# ---------------------------------------------------------------- next slot
def test_next_check_est_monday():
    # Mon Nov 2 2026 11:55 AM PT = 19:55 UTC. Next slot is 15:15 ET = 20:15 UTC, checked 20:25.
    assert nc("2026-11-02 19:55") == ("2026-11-02 20:25", "2026-11-02 20:15", "hourly")
    # Exactly at a check time: that one is done, so the next one.
    assert nc("2026-11-02 20:25") == ("2026-11-02 21:25", "2026-11-02 21:15", "hourly")
    # After 17:15 ET the next is the full run 18:30 ET = 23:30 UTC.
    assert nc("2026-11-02 22:30") == ("2026-11-02 23:40", "2026-11-02 23:30", "full")
    # After the full run: Tuesday 10:15 ET = 15:15 UTC.
    assert nc("2026-11-02 23:40") == ("2026-11-03 15:25", "2026-11-03 15:15", "hourly")


def test_next_check_edt():
    # Fri Oct 30 2026 is EDT: first slot 14:15 UTC, full 22:30 UTC.
    assert nc("2026-10-30 12:00") == ("2026-10-30 14:25", "2026-10-30 14:15", "hourly")
    assert nc("2026-10-30 21:30") == ("2026-10-30 22:40", "2026-10-30 22:30", "full")


def test_friday_to_monday_across_dst_end():
    # Fri Oct 30 full run (EDT) checked 22:40 UTC; next is Mon Nov 2 10:15 EST = 15:15 UTC.
    assert nc("2026-10-30 22:40") == ("2026-11-02 15:25", "2026-11-02 15:15", "hourly")
    assert nc("2026-10-31 12:00") == ("2026-11-02 15:25", "2026-11-02 15:15", "hourly")  # Saturday
    assert nc("2026-11-01 23:59") == ("2026-11-02 15:25", "2026-11-02 15:15", "hourly")  # Sunday night


def test_friday_to_monday_across_dst_start_2027():
    # Fri Mar 12 2027 is EST (full 23:30 UTC); Mon Mar 15 is EDT (first slot 14:15 UTC).
    assert nc("2027-03-12 23:40") == ("2027-03-15 14:25", "2027-03-15 14:15", "hourly")


def test_holidays_are_skipped():
    # Wed Nov 25 2026 full run, Thu Nov 26 Thanksgiving closed, Fri Nov 27 (early close) has slots.
    assert nc("2026-11-25 23:40") == ("2026-11-27 15:25", "2026-11-27 15:15", "hourly")
    # Christmas Fri Dec 25 2026: Thu Dec 24 full run -> Mon Dec 28.
    assert nc("2026-12-24 23:40") == ("2026-12-28 15:25", "2026-12-28 15:15", "hourly")
    # New Year Fri Jan 1 2027 -> Mon Jan 4.
    assert nc("2026-12-31 23:40") == ("2027-01-04 15:25", "2027-01-04 15:15", "hourly")
    # Good Friday Mar 26 2027 (EDT) -> Mon Mar 29 14:15 UTC.
    assert nc("2027-03-25 22:40") == ("2027-03-29 14:25", "2027-03-29 14:15", "hourly")
    # MLK Mon Jan 18 2027: Fri Jan 15 full run -> Tue Jan 19.
    assert nc("2027-01-15 23:40") == ("2027-01-19 15:25", "2027-01-19 15:15", "hourly")
    # Independence Day observed Mon Jul 5 2027 -> Tue Jul 6 (EDT).
    assert nc("2027-07-02 22:40") == ("2027-07-06 14:25", "2027-07-06 14:15", "hourly")
    assert len(w.NYSE_HOLIDAYS) == 20
    assert all(d.weekday() < 5 for d in w.NYSE_HOLIDAYS)
    assert w.market_slots_for_day(dt.date(2026, 11, 26)) == []
    assert len(w.market_slots_for_day(dt.date(2026, 11, 27))) == 9


def test_check_after_setting():
    assert nc("2026-11-02 19:55", lag=20) == ("2026-11-02 20:35", "2026-11-02 20:15", "hourly")


# ---------------------------------------------------------------- sleep and hand-off math
def test_plan_and_sleep_short():
    now = T("2026-11-02 19:55")
    kind, when, slot, mode = w.plan(now, now + dt.timedelta(minutes=330))
    assert (kind, when, slot, mode) == ("check", T("2026-11-02 20:25"), T("2026-11-02 20:15"), "hourly")
    assert w.sleep_seconds(now, when) == 30 * 60
    assert w.sleep_seconds(T("2026-11-02 21:00"), when) == 0  # never negative


def test_plan_overnight_hands_off_in_chunks():
    # After Monday's full-run check, Tuesday 15:25 UTC is 15h45m away: three 330-minute keepers.
    now, chunks = T("2026-11-02 23:41"), 0
    while True:
        deadline = now + dt.timedelta(minutes=330)
        kind, when, _, _ = w.plan(now, deadline)
        assert w.sleep_seconds(now, when) <= 330 * 60
        if kind == "check":
            break
        chunks += 1
        now = when
    assert chunks == 2 and when == T("2026-11-03 15:25")


def test_plan_weekend_chunks():
    now, chunks = T("2026-11-06 23:41"), 0   # Fri Nov 6 after the full-run check
    while True:
        kind, when, _, _ = w.plan(now, now + dt.timedelta(minutes=330))
        if kind == "check":
            break
        chunks += 1
        now = when
    assert when == T("2026-11-09 15:25") and chunks == 11  # ~63.7 h / 5.5 h


def test_plan_lookback_after_handoff():
    # The old keeper handed off at 20:20 because 20:25 was past its deadline. The new keeper starts at
    # 20:27 and looks back 15 minutes, so the 20:25 check still happens (at once).
    start = T("2026-11-02 20:27")
    kind, when, slot, _ = w.plan(start, start + dt.timedelta(minutes=330), start - dt.timedelta(minutes=w.LOOKBACK_MIN))
    assert kind == "check" and when == T("2026-11-02 20:25") and slot == T("2026-11-02 20:15")
    assert w.sleep_seconds(start, when) == 0
    # The first keeper today (19:55) does not look back at the 19:15 UTC slot (19:25 check is >15 min ago).
    start = T("2026-11-02 19:55")
    _, when, _, _ = w.plan(start, start + dt.timedelta(minutes=330), start - dt.timedelta(minutes=15))
    assert when == T("2026-11-02 20:25")


def test_settings_are_clamped():
    s = w.keeper_settings({"keeper": {"chunk_min": 999, "check_after_min": 12}})
    assert s["chunk_min"] == 340 and s["check_after_min"] == 12 and s["min_gap_min"] == 50
    assert w.keeper_settings({}) == w.KEEPER_DEFAULTS


# ---------------------------------------------------------------- already ran
SLOT = T("2026-11-02 20:15")
NOW = T("2026-11-02 20:25")


def test_slot_already_ran():
    assert w.slot_already_ran(SLOT, [run(1, "2026-11-02 20:17")], did_work)[0]                  # on time / late cron
    assert w.slot_already_ran(SLOT, [run(1, "2026-11-02 20:15")], did_work)[0]                  # exactly on the slot
    assert w.slot_already_ran(SLOT, [run(1, "2026-11-02 20:19", "in_progress", None)], did_work)[0]
    assert w.slot_already_ran(SLOT, [run(1, "2026-11-02 19:08", "queued", None)], did_work)[0]  # waiting in line
    assert w.slot_already_ran(SLOT, [run(1, "2026-11-02 20:16", conclusion="failure")], did_work)[0]  # never retried
    assert not w.slot_already_ran(SLOT, [run(1, "2026-11-02 19:16")], did_work)[0]              # previous slot only
    assert not w.slot_already_ran(SLOT, [run(1, "2026-11-02 20:16", worked=False)], did_work)[0]  # DST twin, guard-skipped
    assert not w.slot_already_ran(SLOT, [run(1, "2026-11-02 20:16", conclusion="cancelled")], did_work)[0]
    assert not w.slot_already_ran(SLOT, [], did_work)[0]


def test_keeper_decide():
    # Cron skipped 15:15 ET; the 14:15 ET run started on time: make up once, hourly.
    act, why = w.keeper_decide(NOW, SLOT, "hourly", [run(1, "2026-11-02 19:16")], did_work)
    assert act == "dispatch" and "hourly" in why
    # Slot ran: nothing.
    assert w.keeper_decide(NOW, SLOT, "hourly", [run(2, "2026-11-02 20:18"), run(1, "2026-11-02 19:16")], did_work)[0] == "none"
    # Today's manual fix at 19:08 UTC: at the 19:25 check for the 19:15 slot it is 17 min old, so no extra run.
    assert w.keeper_decide(T("2026-11-02 19:25"), T("2026-11-02 19:15"), "hourly", [run(1, "2026-11-02 19:08")], did_work)[0] == "none"
    # But at 20:25 it is 77 min old and 20:15 did not run: one make-up.
    assert w.keeper_decide(NOW, SLOT, "hourly", [run(1, "2026-11-02 19:08")], did_work)[0] == "dispatch"
    # Full slot keeps its mode.
    act, why = w.keeper_decide(T("2026-11-02 23:40"), T("2026-11-02 23:30"), "full", [run(1, "2026-11-02 22:16")], did_work)
    assert act == "dispatch" and "full" in why
    # Monday morning after a dead weekend: nothing since Friday, make up.
    assert w.keeper_decide(T("2026-11-02 15:25"), T("2026-11-02 15:15"), "hourly", [run(1, "2026-10-31 01:44")], did_work)[0] == "dispatch"


def test_make_up_collapses_with_late_cron_in_guard():
    # Keeper make-up created 20:25; the skipped cron then shows up late at 20:31: the guard skips the cron.
    makeup = {"id": 10, "status": "in_progress", "conclusion": None, "created_at": "2026-11-02T20:25:05Z"}
    late = {"id": 11, "status": "in_progress", "conclusion": None, "created_at": "2026-11-02T20:31:00Z"}
    assert w.duplicate(late, [late, makeup])[0] is True
    assert w.duplicate(makeup, [late, makeup])[0] is False


# ---------------------------------------------------------------- one keeper
def K(i, status):
    return {"id": i, "status": status}


def test_single_keeper_rules():
    assert w.should_start_keeper([], True)[0] is True
    assert w.should_start_keeper([K(1, "completed"), K(2, "cancelled")], True)[0] is True
    for st in ("in_progress", "queued", "pending", "waiting", "requested"):
        assert w.should_start_keeper([K(3, st)], True)[0] is False
    assert w.should_start_keeper([], False)[0] is False        # switch off: never start
    assert w.should_yield(5, [K(5, "in_progress"), K(6, "pending")])[0] is True   # newer one takes over
    assert w.should_yield(6, [K(5, "in_progress"), K(6, "in_progress")])[0] is False
    assert w.should_yield(5, [K(5, "in_progress"), K(4, "completed")])[0] is False
    assert w.live_keepers([K(5, "in_progress"), K(6, "pending")], 5) == [K(6, "pending")]


def test_switch_and_settings_rows():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    assert w.keeper_on(cfg) is True and cfg["features"]["self_heal_keeper"] is True
    assert w.keeper_on({"features": {"self_heal_keeper": False}}) is False
    assert w.keeper_on({}) is True
    rows = dict(zip(tables.settings_rows(cfg)["setting"], tables.settings_rows(cfg)["value"]))
    assert rows["feature.self_heal_keeper"] is True
    assert rows["keeper.check_after_min"] == 10 and rows["keeper.chunk_min"] == 330 and rows["keeper.min_gap_min"] == 50
    assert "self_heal_keeper" in dict(tables.help_rows())["Update keeper"]
    csv = open(os.path.join(ROOT, "data", "settings.csv")).read()
    assert "feature.self_heal_keeper,True" in csv and "keeper.chunk_min,330" in csv
    assert "\nUpdate keeper," in open(os.path.join(ROOT, "data", "help.csv")).read()


# ---------------------------------------------------------------- the loop, fake clock and fake API
class Fake:
    def __init__(self, start, update_runs, keeper_runs, cfgs=None):
        self.t = start
        self.update_runs = update_runs
        self.keeper_runs = keeper_runs
        self.cfgs = list(cfgs or [])
        self.dispatched = []
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += dt.timedelta(seconds=s)

    def config(self, path="config.json"):
        # The loop tests below were written for the eight hourly slots. The
        # twice-daily switch defaults on in config.json; these fakes turn it off.
        return self.cfgs.pop(0) if self.cfgs else {
            "features": {"self_heal_keeper": True, "twice_daily_schedule": False},
        }


def with_fake(f, fn):
    saved = (w.live_config, w.fetch_keeper_runs, w.fetch_runs, w._dispatch, w.api_did_work, w.fetch_price_as_of, w.record)
    w.live_config = f.config
    w.fetch_price_as_of = lambda: getattr(f, "asof", None)
    f.records = []
    w.record = lambda level, text: f.records.append((level, text))
    w.fetch_keeper_runs = lambda n=20: f.keeper_runs
    w.fetch_runs = lambda n=50: f.update_runs
    w._dispatch = lambda wf, inputs, tries=3: f.dispatched.append((wf, inputs)) or True
    w.api_did_work = did_work
    try:
        return fn()
    finally:
        (w.live_config, w.fetch_keeper_runs, w.fetch_runs, w._dispatch, w.api_did_work,
         w.fetch_price_as_of, w.record) = saved
        w.TWICE_DAILY = False


def test_loop_makes_up_missed_slots_then_hands_off():
    # Start Mon 19:55 UTC with the 19:08 manual run only; GitHub cron is dead all day.
    f = Fake(T("2026-11-02 19:55"), [run(1, "2026-11-02 19:08")], [K(100, "in_progress")])
    real_dispatch = []

    def dispatch(wf, inputs, tries=3):
        real_dispatch.append((wf, inputs, f.t))
        if wf == w.WORKFLOW_FILE:  # the make-up starts a run at once
            f.update_runs.insert(0, run(len(f.update_runs) + 2, f.t.strftime("%Y-%m-%d %H:%M")))
        return True

    def go():
        w._dispatch = dispatch
        return w.run_keeper({"GITHUB_RUN_ID": "100"}, now=f.now, sleep=f.sleep)
    assert with_fake(f, go) == "handoff"
    ups = [(i["mode"], t.strftime("%H:%M")) for wf, i, t in real_dispatch if wf == w.WORKFLOW_FILE]
    assert ups == [("hourly", "20:25"), ("hourly", "21:25"), ("hourly", "22:25"), ("full", "23:40")]
    assert all(i.get("reason") == "keeper" for wf, i, _ in real_dispatch if wf == w.WORKFLOW_FILE)
    assert real_dispatch[-1][0] == w.KEEPER_FILE and real_dispatch[-1][2] == T("2026-11-03 01:25")  # 330 min
    assert max(f.slept) <= 330 * 60


def test_loop_does_nothing_when_crons_fire():
    f = Fake(T("2026-11-02 19:55"), [], [K(100, "in_progress")])
    cron_starts = ["2026-11-02 20:17", "2026-11-02 21:16", "2026-11-02 22:19", "2026-11-02 23:33"]

    def sleep(s):
        f.sleep(s)
        for c in cron_starts:
            if T(c) <= f.t and all(r["created_at"] != T(c).strftime("%Y-%m-%dT%H:%M:%SZ") for r in f.update_runs):
                f.update_runs.insert(0, run(len(f.update_runs) + 2, c))
    with_fake(f, lambda: w.run_keeper({"GITHUB_RUN_ID": "100"}, now=f.now, sleep=sleep))
    assert [d for d in f.dispatched if d[0] == w.WORKFLOW_FILE] == []
    assert f.dispatched == [(w.KEEPER_FILE, {})]


def test_loop_switch_off_stops_without_chaining():
    f = Fake(T("2026-11-02 19:55"), [], [K(100, "in_progress")],
             cfgs=[{"features": {"self_heal_keeper": True}}, {"features": {"self_heal_keeper": False}}])
    assert with_fake(f, lambda: w.run_keeper({"GITHUB_RUN_ID": "100"}, now=f.now, sleep=f.sleep)) == "off"
    assert f.dispatched == []
    f = Fake(T("2026-11-02 19:55"), [], [], cfgs=[{"features": {"self_heal_keeper": False}}])
    assert with_fake(f, lambda: w.run_keeper({"GITHUB_RUN_ID": "100"}, now=f.now, sleep=f.sleep)) == "off"
    assert f.slept == [] and f.dispatched == []


def test_loop_yields_to_newer_keeper_and_does_not_fork():
    f = Fake(T("2026-11-02 19:55"), [], [K(100, "in_progress"), K(101, "pending")])
    assert with_fake(f, lambda: w.run_keeper({"GITHUB_RUN_ID": "100"}, now=f.now, sleep=f.sleep)) == "yield"
    assert f.dispatched == [] and f.slept == []
    # At hand-off time an older-id stray keeper is queued: do not add another.
    f = Fake(T("2026-11-02 23:45"), [run(1, "2026-11-02 23:31")], [K(100, "in_progress"), K(99, "queued")])
    assert with_fake(f, lambda: w.run_keeper({"GITHUB_RUN_ID": "100"}, now=f.now, sleep=f.sleep)) == "yield"
    assert f.dispatched == []


def test_ensure_keeper():
    f = Fake(T("2026-11-02 19:55"), [], [K(100, "in_progress")])
    assert with_fake(f, lambda: w.ensure_keeper({"features": {}})) is False and f.dispatched == []
    f = Fake(T("2026-11-02 19:55"), [], [K(100, "completed")])
    assert with_fake(f, lambda: w.ensure_keeper({"features": {}})) is True and f.dispatched == [(w.KEEPER_FILE, {})]
    f = Fake(T("2026-11-02 19:55"), [], [])
    assert with_fake(f, lambda: w.ensure_keeper({"features": {}}, dry=True)) is False and f.dispatched == []
    assert with_fake(f, lambda: w.ensure_keeper({"features": {"self_heal_keeper": False}})) is False and f.dispatched == []


# ---------------------------------------------------------------- success and fresh data, retry once
def ev(after, lag=10, verify=45):
    kind, when, slot, mode = w.next_event(T(after), lag, verify)
    return kind, when.strftime("%Y-%m-%d %H:%M"), slot.strftime("%H:%M"), mode


def test_next_event_with_verify():
    assert ev("2026-11-02 19:55") == ("verify", "2026-11-02 20:00", "19:15", "hourly")
    assert ev("2026-11-02 20:00") == ("check", "2026-11-02 20:25", "20:15", "hourly")
    assert ev("2026-11-02 20:25") == ("verify", "2026-11-02 21:00", "20:15", "hourly")
    assert ev("2026-11-02 21:00") == ("check", "2026-11-02 21:25", "21:15", "hourly")
    assert ev("2026-11-02 23:40") == ("verify", "2026-11-03 00:15", "23:30", "full")   # full run verified 19:15 ET
    assert ev("2026-11-03 00:15") == ("check", "2026-11-03 15:25", "15:15", "hourly")
    assert ev("2026-10-30 23:15") == ("check", "2026-11-02 15:25", "15:15", "hourly")  # Fri EDT verify done -> Mon EST
    assert ev("2026-11-25 23:40") == ("verify", "2026-11-26 00:15", "23:30", "full")   # Wed before Thanksgiving
    assert ev("2026-11-26 00:15") == ("check", "2026-11-27 15:25", "15:15", "hourly")
    assert w.next_slot_start(T("2026-11-02 23:30")) == T("2026-11-03 15:15")
    assert w.next_slot_start(T("2026-11-02 20:15")) == T("2026-11-02 21:15")


def test_plan_prefers_due_recheck():
    now = T("2026-11-02 21:00")
    kind, when, slot, _ = w.plan(now, now + dt.timedelta(minutes=330), now, 10, 45,
                                 [(T("2026-11-02 21:15"), T("2026-11-02 20:15"), "hourly")])
    assert (kind, when, slot) == ("verify", T("2026-11-02 21:15"), T("2026-11-02 20:15"))


def test_verify_decide():
    S, U = T("2026-11-02 20:15"), T("2026-11-02 21:15")
    V = lambda runs, asof="2026-11-02", tries=2: w.verify_decide(S, "hourly", runs, asof, did_work, tries, U)[0]
    assert V([run(1, "2026-11-02 20:17")]) == "ok"
    assert V([run(1, "2026-11-02 20:17")], asof="2026-10-30") == "stale"           # success but data did not move
    assert V([run(1, "2026-11-02 20:17")], asof=None) == "ok"                      # unreadable: no false alarm
    assert V([run(1, "2026-11-02 20:17", conclusion="failure")]) == "retry"         # India case: failed on a test
    assert V([run(1, "2026-11-02 20:17", conclusion="timed_out")]) == "retry"
    assert V([run(2, "2026-11-02 21:01", conclusion="failure"), run(1, "2026-11-02 20:17", conclusion="failure")]) == "gave_up"
    assert V([run(2, "2026-11-02 21:01"), run(1, "2026-11-02 20:17", conclusion="failure")]) == "ok"  # retry worked
    assert V([run(1, "2026-11-02 20:17", conclusion="failure")], tries=1) == "gave_up"
    assert V([run(1, "2026-11-02 20:40", "in_progress", None)]) == "wait"
    assert V([]) == "none" and V([run(1, "2026-11-02 19:16")]) == "none"            # earlier slot's run is not this slot's
    assert V([run(1, "2026-11-02 20:17", conclusion="cancelled")]) == "none"
    assert V([run(1, "2026-11-02 20:17", worked=False)]) == "none"                  # guard-skipped twin
    assert V([run(3, "2026-11-02 21:16", conclusion="failure")]) == "none"          # next slot's run is not this slot's
    # Full slot: price_as_of must be that New York date, even though it is the next UTC day.
    full = w.verify_decide(T("2026-11-02 23:30"), "full", [run(1, "2026-11-02 23:31")], "2026-11-02", did_work, 2,
                           T("2026-11-03 15:15"))
    assert full[0] == "ok"


def test_retry_cap_setting():
    assert w.keeper_settings({"keeper": {"max_tries": 9}})["max_tries"] == 2
    assert w.keeper_settings({"keeper": {"max_tries": 0}})["max_tries"] == 1


def test_loop_retries_a_failed_slot_once_then_records():
    # Cron runs fire on time but every run fails (like the India desk failing a test). Mon 20:15 slot.
    f = Fake(T("2026-11-02 19:55"), [], [K(100, "in_progress")])
    f.asof = "2026-11-02"
    sent = []

    def dispatch(wf, inputs, tries=3):
        sent.append((wf, inputs.get("reason"), f.t.strftime("%H:%M")))
        if wf == w.WORKFLOW_FILE:
            f.update_runs.insert(0, run(500 + len(sent), f.t.strftime("%Y-%m-%d %H:%M"), conclusion="failure"))
        return True

    def sleep(s):
        f.sleep(s)
        for c in ("2026-11-02 20:16", "2026-11-02 21:16", "2026-11-02 22:16", "2026-11-02 23:31"):
            stamp = T(c).strftime("%Y-%m-%dT%H:%M:%SZ")
            if T(c) <= f.t and all(r["created_at"] != stamp for r in f.update_runs):
                f.update_runs.insert(0, run(len(f.update_runs) + 2, c, conclusion="failure"))

    def go():
        w._dispatch = dispatch
        return w.run_keeper({"GITHUB_RUN_ID": "100"}, now=f.now, sleep=sleep)
    assert with_fake(f, go) == "handoff"
    retries = [x for x in sent if x[1] == "keeper_retry"]
    assert retries == [("update.yml", "keeper_retry", "21:00"), ("update.yml", "keeper_retry", "22:00"),
                       ("update.yml", "keeper_retry", "23:00"), ("update.yml", "keeper_retry", "00:15")]  # one per slot
    assert [x for x in sent if x[1] == "keeper"] == []              # cron runs existed, no make-ups
    gave_up = [t for lvl, t in f.records if "not retrying again" in t]
    assert len(gave_up) == 4 and all(lvl == "warning" for lvl, _ in f.records)  # each slot: one retry, then recorded


def test_loop_records_stale_data_without_retry():
    f = Fake(T("2026-11-02 19:55"), [], [K(100, "in_progress")])
    f.asof = "2026-10-30"

    def sleep(s):
        f.sleep(s)
        stamp = "2026-11-02T20:16:00Z"
        if T("2026-11-02 20:16") <= f.t and all(r["created_at"] != stamp for r in f.update_runs):
            f.update_runs.insert(0, run(7, "2026-11-02 20:16"))
    with_fake(f, lambda: w.run_keeper({"GITHUB_RUN_ID": "100"}, now=f.now, sleep=sleep))
    assert any("price_as_of is 2026-10-30" in t for _, t in f.records)
    assert [d for d in f.dispatched if d[1].get("reason") == "keeper_retry"] == []


def test_loop_waits_for_a_long_run():
    f = Fake(T("2026-11-02 23:41"), [run(1, "2026-11-02 23:31", "in_progress", None)], [K(100, "in_progress")])
    f.asof = "2026-11-02"

    def sleep(s):
        f.sleep(s)
        if f.t >= T("2026-11-03 00:40"):
            f.update_runs[0] = run(1, "2026-11-02 23:31")
    with_fake(f, lambda: w.run_keeper({"GITHUB_RUN_ID": "100"}, now=f.now, sleep=sleep))
    assert f.dispatched == [(w.KEEPER_FILE, {})] and f.records == []


def test_workflows_wired():
    wf = lambda n: open(os.path.join(ROOT, ".github", "workflows", n)).read()
    keeper, update, dog = wf("keeper.yml"), wf("update.yml"), wf("watchdog.yml")
    assert "workflow_dispatch" in keeper and "schedule" not in keeper
    assert "group: update-keeper" in keeper and "actions: write" in keeper
    assert "timeout-minutes: 350" in keeper and "watchdog.py keeper" in keeper
    assert "inputs.reason == 'keeper'" in update and "watchdog.py ensure-keeper" in update
    guard_if = [l for l in update.splitlines() if "github.event_name == 'schedule'" in l][0]
    assert "keeper_retry" not in guard_if   # the one retry is not collapsed by the duplicate guard
    assert "python tests/test_keeper.py" in update
    assert "watchdog.py ensure-keeper" in dog


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("keeper ok")
