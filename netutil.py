"""Network helpers for Nick's Stock Desk.

Rate limits are part of the design, not an afterthought:
- a shared gate keeps SEC EDGAR under the configured requests per second
- call_with_retry waits with exponential backoff on 429 and transient errors
- slow sources (fundamentals, analyst, 13F, insider, option chains) refresh at most once a day
- a failed fetch falls back to the cache and is marked CACHED
"""
import time
import threading


class RetryableError(Exception):
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class PermanentError(Exception):
    pass


class RateLimiter:
    """Spaces out call starts so a host stays under a requests-per-second cap."""

    def __init__(self, per_second, sleep=None, clock=None):
        self.min_interval = 1.0 / float(per_second) if per_second else 0.0
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self.lock = threading.Lock()
        self.next_ok = 0.0

    def wait(self):
        if self.min_interval <= 0:
            return
        with self.lock:
            now = self.clock()
            delay = self.next_ok - now
            if delay > 0:
                self.sleep(delay)
                now = self.clock()
            self.next_ok = now + self.min_interval


def is_permanent_message(exc):
    msg = str(exc).lower()
    return any(s in msg for s in ("delisted", "no data found", "not found", "invalid ticker", "404"))


def call_with_retry(fn, max_tries=4, delays=(1.5, 3.0, 6.0, 12.0), sleep=None):
    """Run fn. On a transient error, wait and try again. Delays double each time."""
    sleep = sleep or time.sleep
    last = None
    tries = max(1, int(max_tries))
    for i in range(tries):
        try:
            return fn()
        except PermanentError:
            raise
        except Exception as exc:
            last = exc
            if is_permanent_message(exc):
                raise
            if i == tries - 1:
                break
            wait = exc.retry_after if isinstance(exc, RetryableError) and exc.retry_after else delays[min(i, len(delays) - 1)]
            sleep(float(wait))
    raise last


def http_get(session, url, headers, timeout, limiter=None, max_tries=4, delays=(1.5, 3.0, 6.0, 12.0), sleep=None):
    """GET with the rate gate and backoff. 429 and 5xx are retried. 403 and 404 are not."""

    def once():
        if limiter is not None:
            limiter.wait()
        r = session.get(url, headers=headers, timeout=timeout)
        code = r.status_code
        if code == 429 or code >= 500:
            retry_after = None
            try:
                retry_after = float(r.headers.get("Retry-After"))
            except (TypeError, ValueError):
                retry_after = None
            raise RetryableError("HTTP %s for %s" % (code, url), retry_after=retry_after)
        if code in (403, 404):
            raise PermanentError("HTTP %s for %s" % (code, url))
        r.raise_for_status()
        return r

    return call_with_retry(once, max_tries=max_tries, delays=delays, sleep=sleep)


def decide_slow(stamp, today, cache_exists, mode, force=False):
    """What to do with a slow source.

    hourly and offline never call the network (reuse the cache, or MISSING).
    full fetches when the cache is not already from today's US session.
    """
    if mode in ("hourly", "offline"):
        return "reuse" if cache_exists else "missing"
    if force:
        return "fetch"
    if stamp == today and cache_exists:
        return "reuse"
    return "fetch"


def status_after_fetch(ok, cache_exists):
    if ok:
        return "OK"
    if cache_exists:
        return "CACHED"
    return "MISSING"
