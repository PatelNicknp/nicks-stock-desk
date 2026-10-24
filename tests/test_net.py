"""Rate gate, backoff, and the once-a-day cache decision."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import netutil


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_gate_spaces_calls():
    c = Clock()
    gate = netutil.RateLimiter(10, sleep=c.sleep, clock=c.clock)  # 0.1s apart
    gate.wait()
    gate.wait()
    gate.wait()
    assert len(c.slept) == 2
    assert abs(sum(c.slept) - 0.2) < 1e-9


def test_retry_backs_off_then_succeeds():
    waits = []
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise netutil.RetryableError("429", retry_after=None)
        return "ok"

    out = netutil.call_with_retry(fn, max_tries=4, delays=(1, 2, 4), sleep=waits.append)
    assert out == "ok"
    assert waits == [1, 2]


def test_permanent_does_not_retry():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise netutil.PermanentError("403")

    try:
        netutil.call_with_retry(fn, max_tries=4, sleep=lambda s: None)
        assert False
    except netutil.PermanentError:
        pass
    assert calls["n"] == 1


def test_slow_source_decisions():
    assert netutil.decide_slow("2026-10-23", "2026-10-24", True, "hourly") == "reuse"
    assert netutil.decide_slow(None, "2026-10-24", False, "hourly") == "missing"
    assert netutil.decide_slow("2026-10-24", "2026-10-24", True, "full") == "reuse"
    assert netutil.decide_slow("2026-10-23", "2026-10-24", True, "full") == "fetch"
    assert netutil.decide_slow("2026-10-24", "2026-10-24", True, "full", force=True) == "fetch"
    assert netutil.decide_slow(None, "2026-10-24", False, "offline") == "missing"
    assert netutil.status_after_fetch(False, True) == "CACHED"
    assert netutil.status_after_fetch(False, False) == "MISSING"
    assert netutil.status_after_fetch(True, False) == "OK"


if __name__ == "__main__":
    test_gate_spaces_calls()
    test_retry_backs_off_then_succeeds()
    test_permanent_does_not_retry()
    test_slow_source_decisions()
    print("net ok")
