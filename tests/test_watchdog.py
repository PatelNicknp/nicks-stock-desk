"""Offline checks for the New York-time schedule and the watchdog. No network.

DST in 2026: EDT until Sunday Nov 1 (UTC-4), EST after (UTC-5).
DST in 2027 starts Sunday Mar 14 (EST -> EDT). 2026-10-26 is a Monday.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import watchdog as w

UTC = dt.timezone.utc
HOURLY = "15 14-22 * * 1-5"
FULL = "30 22,23 * * 1-5"


def T(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def run(i, start, status="completed", conclusion="success", event="schedule", worked=True):
    stamp = T(start).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": i, "status": status, "conclusion": conclusion, "event": event,
            "created_at": stamp, "run_started_at": stamp, "_worked": worked}


def did_work(r):
    return r.get("_worked", True)


def utc_slots(day):
    return [(t.strftime("%H:%M"), m) for t, m in w.slots_for_day(dt.date.fromisoformat(day))]


def fired(day, cron):
    """Every UTC fire time of `cron` on a UTC date, with the gate's verdict."""
    out = []
    for h in range(24):
        for m in (15, 30):
            t = T("%s %02d:%02d" % (day, h, m))
            if w.cron_fire_time(cron, t) == t:
                go, mode, _ = w.schedule_gate(cron, t + dt.timedelta(minutes=3))
                out.append((t.strftime("%H:%M"), go, mode))
    return out


def test_slots_before_and_after_nov_1_2026():
    edt = ["14:15", "15:15", "16:15", "17:15", "18:15", "19:15", "20:15", "21:15"]
    est = ["15:15", "16:15", "17:15", "18:15", "19:15", "20:15", "21:15", "22:15"]
    assert utc_slots("2026-10-30") == [(t, "hourly") for t in edt] + [("22:30", "full")]  # Fri, EDT
    assert utc_slots("2026-11-02") == [(t, "hourly") for t in est] + [("23:30", "full")]  # Mon, EST
    assert utc_slots("2026-10-31") == [] and utc_slots("2026-11-01") == []                # weekend


def test_slots_across_march_2027():
    assert utc_slots("2027-03-12")[0] == ("15:15", "hourly") and utc_slots("2027-03-12")[-1] == ("23:30", "full")  # Fri, EST
    assert utc_slots("2027-03-15")[0] == ("14:15", "hourly") and utc_slots("2027-03-15")[-1] == ("22:30", "full")  # Mon, EDT


def test_slots_in_pacific_time_do_not_move():
    pt = w.ZoneInfo("America/Los_Angeles")
    for day in ("2026-10-30", "2026-11-02", "2027-03-12", "2027-03-15"):
        got = [t.astimezone(pt).strftime("%H:%M") for t, _ in w.slots_for_day(dt.date.fromisoformat(day))]
        assert got == ["07:15", "08:15", "09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:30"], (day, got)


def test_gate_lets_one_cron_per_slot_through_edt():
    # Friday Oct 30 2026, EDT. 14:15-21:15 run, 22:15 (18:15 ET) is skipped.
    h = fired("2026-10-30", HOURLY)
    assert [t for t, go, _ in h if go] == ["14:15", "15:15", "16:15", "17:15", "18:15", "19:15", "20:15", "21:15"]
    assert [t for t, go, _ in h if not go] == ["22:15"]
    assert all(m == "hourly" for _, go, m in h if go)
    f = fired("2026-10-30", FULL)
    assert f == [("22:30", True, "full"), ("23:30", False, None)]


def test_gate_lets_one_cron_per_slot_through_est():
    # Monday Nov 2 2026, EST. 14:15 (9:15 ET) is skipped, 15:15-22:15 run.
    h = fired("2026-11-02", HOURLY)
    assert [t for t, go, _ in h if not go] == ["14:15"]
    assert [t for t, go, _ in h if go] == ["15:15", "16:15", "17:15", "18:15", "19:15", "20:15", "21:15", "22:15"]
    f = fired("2026-11-02", FULL)
    assert f == [("22:30", False, None), ("23:30", True, "full")]  # 22:30 UTC is 17:30 ET


def test_gate_across_march_2027():
    assert [t for t, go, _ in fired("2027-03-12", HOURLY) if not go] == ["14:15"]   # EST
    assert [t for t, go, _ in fired("2027-03-15", HOURLY) if not go] == ["22:15"]   # EDT
    assert fired("2027-03-15", FULL) == [("22:30", True, "full"), ("23:30", False, None)]


def test_gate_counts_runs_per_week_unchanged():
    # Nine real runs per weekday, before and after the change: same Yahoo traffic.
    for days in (("2026-10-26", "2026-10-30"), ("2026-11-02", "2026-11-06"), ("2027-03-08", "2027-03-12"), ("2027-03-15", "2027-03-19")):
        d0 = dt.date.fromisoformat(days[0])
        total = 0
        for k in range(5):
            day = (d0 + dt.timedelta(days=k)).isoformat()
            total += sum(1 for _, go, _ in fired(day, HOURLY) + fired(day, FULL) if go)
        assert total == 45, (days, total)


def test_gate_handles_a_late_cron_and_unknown_cron():
    # 15:15 UTC cron (10:15 EST) delivered 25 minutes late is still the 10:15 slot.
    go, mode, _ = w.schedule_gate(HOURLY, T("2026-11-02 15:40"))
    assert go and mode == "hourly"
    go, mode, _ = w.schedule_gate("", T("2026-11-02 15:40"))
    assert go and mode == "hourly"  # unknown cron: run as before
    # A full-run cron delivered late is still judged by the time it was due.
    go, mode, _ = w.schedule_gate(FULL, T("2026-11-02 23:58"))
    assert go and mode == "full"
    go, mode, _ = w.schedule_gate(FULL, T("2026-11-02 22:58"))
    assert go is False  # that is the 22:30 UTC (17:30 ET) twin


def test_last_slot():
    slot, mode = w.last_slot(T("2026-10-26 22:40"))
    assert slot == T("2026-10-26 22:30") and mode == "full"
    slot, mode = w.last_slot(T("2026-11-02 23:00"))
    assert slot == T("2026-11-02 22:15") and mode == "hourly"
    slot, mode = w.last_slot(T("2026-11-02 23:45"))
    assert slot == T("2026-11-02 23:30") and mode == "full"
    slot, _ = w.last_slot(T("2026-11-02 12:00"))  # Monday morning -> Friday's full run (EDT)
    assert slot == T("2026-10-30 22:30")


def test_on_time_does_nothing():
    runs = [run(2, "2026-10-26 15:17"), run(1, "2026-10-26 14:18")]
    assert w.decide(T("2026-10-26 15:52"), runs)[0] == "none"
    assert w.decide(T("2026-10-26 16:22"), runs)[0] == "none"


def test_missed_slot_dispatches_once():
    runs = [run(1, "2026-10-26 14:18")]
    action, why, mode = w.decide(T("2026-10-26 15:37"), runs)
    assert action == "dispatch" and mode == "hourly", why
    queued = [run(3, "2026-10-26 15:37", status="queued", conclusion=None, event="workflow_dispatch")] + runs
    assert w.decide(T("2026-10-26 15:52"), queued)[0] == "none"
    done = [run(3, "2026-10-26 15:37", event="workflow_dispatch")] + runs
    assert w.decide(T("2026-10-26 15:52"), done)[0] == "none"
    assert w.decide(T("2026-10-26 16:07"), done)[0] == "none"


def test_full_slot_after_nov_1_and_the_skipped_twin():
    # EST: last hourly 22:15 UTC ran, 23:30 UTC full run missed. A skipped twin cron
    # (22:30 UTC = 17:30 ET) does not count as a run.
    runs = [run(2, "2026-11-02 22:31", worked=False), run(1, "2026-11-02 22:16")]
    action, why, mode = w.decide(T("2026-11-02 23:52"), runs, did_work=did_work)
    assert action == "dispatch" and mode == "full", why
    # A skipped 19:30 ET twin after the slot does not hide the missed full run either.
    action, _, mode = w.decide(T("2026-11-03 00:07"), [run(3, "2026-11-02 23:31", worked=False)] + runs, did_work=did_work)
    assert action == "dispatch" and mode == "full"


def test_full_slot_edt():
    runs = [run(1, "2026-10-26 21:16")]
    action, _, mode = w.decide(T("2026-10-26 22:52"), runs)
    assert action == "dispatch" and mode == "full"


def test_recent_manual_run_counts():
    runs = [run(2, "2026-10-26 15:00", event="workflow_dispatch"), run(1, "2026-10-26 14:16")]
    assert w.decide(T("2026-10-26 15:37"), runs)[0] == "none"


def test_in_progress_switch_failed_cancelled():
    busy = [run(2, "2026-10-26 14:16", status="in_progress", conclusion=None)]
    assert w.decide(T("2026-10-26 16:07"), busy)[0] == "none"
    assert w.decide(T("2026-10-26 15:37"), [run(1, "2026-10-26 14:16")], enabled=False)[0] == "none"
    failed = [run(2, "2026-10-26 15:16", conclusion="failure"), run(1, "2026-10-26 14:16")]
    assert w.decide(T("2026-10-26 15:52"), failed)[0] == "none"
    cancelled = [run(2, "2026-10-26 15:16", conclusion="cancelled"), run(1, "2026-10-26 14:16")]
    assert w.decide(T("2026-10-26 15:52"), cancelled)[0] == "dispatch"


def test_weekend_and_too_old():
    runs = [run(1, "2026-10-23 22:31")]
    assert w.decide(T("2026-10-24 15:00"), runs)[0] == "none"
    assert w.decide(T("2026-10-26 13:00"), runs)[0] == "none"
    assert w.decide(T("2026-10-24 03:00"), [run(1, "2026-10-23 21:16")])[0] == "none"


def test_duplicate_guard():
    makeup = run(3, "2026-10-26 15:37", event="workflow_dispatch")
    late_cron = run(4, "2026-10-26 15:49")
    prior = run(1, "2026-10-26 14:18")
    assert w.duplicate(late_cron, [late_cron, makeup, prior])[0]
    assert not w.duplicate(makeup, [late_cron, makeup, prior])[0]
    nxt = run(5, "2026-10-26 16:16")
    assert not w.duplicate(nxt, [nxt, late_cron, makeup, prior])[0]
    cancelled = run(3, "2026-10-26 15:37", conclusion="cancelled", event="workflow_dispatch")
    assert not w.duplicate(late_cron, [late_cron, cancelled, prior])[0]
    # A skipped DST twin inside the slot does not make the real run step aside.
    twin = run(6, "2026-11-02 22:31", worked=False)      # 17:30 ET twin, skipped
    real_full = run(7, "2026-11-02 23:33")               # 18:30 ET
    assert not w.duplicate(real_full, [real_full, twin], did_work)[0]


def test_run_guard_end_to_end():
    def runs():
        return [{"id": 9, "status": "in_progress", "conclusion": None, "created_at": "2026-11-02T14:15:40Z"}]
    skip, mode = w.run_guard({"EVENT_NAME": "schedule", "SCHEDULE": HOURLY, "GITHUB_RUN_ID": "9"}, fetch=runs)
    assert skip and mode == ""  # 9:15 ET twin
    def runs2():
        return [{"id": 9, "status": "in_progress", "conclusion": None, "created_at": "2026-11-02T23:31:00Z"}]
    skip, mode = w.run_guard({"EVENT_NAME": "schedule", "SCHEDULE": FULL, "GITHUB_RUN_ID": "9"}, fetch=runs2)
    assert not skip and mode == "full"
    def broken():
        raise RuntimeError("no api")
    skip, _ = w.run_guard({"EVENT_NAME": "workflow_dispatch", "GITHUB_RUN_ID": "9"}, fetch=broken)
    assert not skip  # fail open


def test_switch_reads_config():
    assert w.switch_on(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")) is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("watchdog ok")
