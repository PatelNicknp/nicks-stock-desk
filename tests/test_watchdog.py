"""Offline checks for the schedule watchdog. No network."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import watchdog as w

UTC = dt.timezone.utc


def T(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def run(i, start, status="completed", conclusion="success", event="schedule"):
    stamp = T(start).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": i, "status": status, "conclusion": conclusion, "event": event,
            "created_at": stamp, "run_started_at": stamp}


# 2026-10-26 is a Monday.
def test_slots():
    assert len(w.slots_for_day(T("2026-10-26 00:00").date())) == 9
    assert w.slots_for_day(T("2026-10-25 00:00").date()) == []  # Sunday
    slot, mode = w.last_slot(T("2026-10-26 22:40"))
    assert slot == T("2026-10-26 22:30") and mode == "full"
    slot, mode = w.last_slot(T("2026-10-26 15:20"))
    assert slot == T("2026-10-26 15:15") and mode == "hourly"
    slot, _ = w.last_slot(T("2026-10-26 10:00"))  # Monday morning -> Friday's last slot
    assert slot == T("2026-10-23 22:30")


def test_on_time_does_nothing():
    runs = [run(2, "2026-10-26 15:17"), run(1, "2026-10-26 14:18")]
    assert w.decide(T("2026-10-26 15:52"), runs)[0] == "none"
    assert w.decide(T("2026-10-26 16:22"), runs)[0] == "none"  # 16:15 is inside the grace window


def test_missed_slot_dispatches_once():
    runs = [run(1, "2026-10-26 14:18")]
    # 15:15 skipped. At 15:37 the slot is past grace and the last start is 79 min old.
    action, why, mode = w.decide(T("2026-10-26 15:37"), runs)
    assert action == "dispatch" and mode == "hourly", why
    # The make-up run is now queued: no second dispatch.
    queued = [run(3, "2026-10-26 15:37", status="queued", conclusion=None, event="workflow_dispatch")] + runs
    assert w.decide(T("2026-10-26 15:52"), queued)[0] == "none"
    # Once it ran, the slot is covered.
    done = [run(3, "2026-10-26 15:37", event="workflow_dispatch")] + runs
    assert w.decide(T("2026-10-26 15:52"), done)[0] == "none"
    assert w.decide(T("2026-10-26 16:07"), done)[0] == "none"


def test_full_slot_uses_full_mode():
    runs = [run(1, "2026-10-26 21:16")]
    action, _, mode = w.decide(T("2026-10-26 22:52"), runs)
    assert action == "dispatch" and mode == "full"


def test_recent_manual_run_counts():
    runs = [run(2, "2026-10-26 15:00", event="workflow_dispatch"), run(1, "2026-10-26 14:16")]
    # 15:15 slot missed, but a run started 37 minutes ago: not overdue.
    assert w.decide(T("2026-10-26 15:37"), runs)[0] == "none"


def test_in_progress_and_switch_and_failed_and_cancelled():
    busy = [run(2, "2026-10-26 14:16", status="in_progress", conclusion=None)]
    assert w.decide(T("2026-10-26 16:07"), busy)[0] == "none"
    assert w.decide(T("2026-10-26 15:37"), [run(1, "2026-10-26 14:16")], enabled=False)[0] == "none"
    # A failed run still counts as having run: no retry, no extra Yahoo traffic.
    failed = [run(2, "2026-10-26 15:16", conclusion="failure"), run(1, "2026-10-26 14:16")]
    assert w.decide(T("2026-10-26 15:52"), failed)[0] == "none"
    # A cancelled run did not run: the slot is still missed.
    cancelled = [run(2, "2026-10-26 15:16", conclusion="cancelled"), run(1, "2026-10-26 14:16")]
    assert w.decide(T("2026-10-26 15:52"), cancelled)[0] == "dispatch"


def test_weekend_and_too_old():
    runs = [run(1, "2026-10-23 22:31")]
    assert w.decide(T("2026-10-24 15:00"), runs)[0] == "none"  # Saturday, Friday's last slot ran
    assert w.decide(T("2026-10-26 13:00"), runs)[0] == "none"  # Monday before the window
    # Friday's 22:30 missed, but it is now Saturday: too old to make up.
    old = [run(1, "2026-10-23 21:16")]
    assert w.decide(T("2026-10-24 03:00"), old)[0] == "none"


def test_guard_collapses_a_late_cron_and_a_makeup():
    makeup = run(3, "2026-10-26 15:37", event="workflow_dispatch")
    late_cron = run(4, "2026-10-26 15:49")
    prior = run(1, "2026-10-26 14:18")
    skip, _ = w.guard(late_cron, [late_cron, makeup, prior])
    assert skip
    first, _ = w.guard(makeup, [late_cron, makeup, prior])
    assert not first
    # Next slot's cron is not affected.
    nxt = run(5, "2026-10-26 16:16")
    assert not w.guard(nxt, [nxt, late_cron, makeup, prior])[0]
    # Switch off: never skip.
    assert not w.guard(late_cron, [late_cron, makeup, prior], enabled=False)[0]
    # A cancelled earlier run does not cover the slot.
    cancelled = run(3, "2026-10-26 15:37", conclusion="cancelled", event="workflow_dispatch")
    assert not w.guard(late_cron, [late_cron, cancelled, prior])[0]


def test_switch_reads_config():
    assert w.switch_on(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")) is True


if __name__ == "__main__":
    test_slots()
    test_on_time_does_nothing()
    test_missed_slot_dispatches_once()
    test_full_slot_uses_full_mode()
    test_recent_manual_run_counts()
    test_in_progress_and_switch_and_failed_and_cancelled()
    test_weekend_and_too_old()
    test_guard_collapses_a_late_cron_and_a_makeup()
    test_switch_reads_config()
    print("watchdog ok")
