"""Black-Scholes price, delta, and implied vol. No dividends. No scipy.

The solver is a bisection over the same 0.001 to 5.0 vol range the mentor
uses. A price at or inside intrinsic, or a non-positive time, has no IV.
"""
import math

_SQRT2 = math.sqrt(2.0)
_IV_LO = 1e-3
_IV_HI = 5.0


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def d1d2(S, K, T, r, s):
    vol = s * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * s * s) * T) / vol
    return d1, d1 - vol


def price(S, K, T, r, s, kind):
    if T <= 0 or s <= 0 or S <= 0 or K <= 0:
        intrinsic = max(0.0, S - K) if kind == "call" else max(0.0, K - S)
        return float(intrinsic)
    d1, d2 = d1d2(S, K, T, r, s)
    disc = math.exp(-r * T)
    if kind == "call":
        return S * norm_cdf(d1) - K * disc * norm_cdf(d2)
    return K * disc * norm_cdf(-d2) - S * norm_cdf(-d1)


def delta(S, K, T, r, s, kind):
    if T <= 0 or s <= 0 or S <= 0 or K <= 0:
        if kind == "call":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0
    d1, _ = d1d2(S, K, T, r, s)
    if kind == "call":
        return norm_cdf(d1)
    return norm_cdf(d1) - 1.0


def implied_vol(px, S, K, T, r, kind):
    """IV from a mid price. None when the price is not above intrinsic."""
    if px is None or S <= 0 or K <= 0 or T <= 0:
        return None
    intrinsic = max(0.0, S - K) if kind == "call" else max(0.0, K - S)
    if px <= intrinsic + 1e-4:
        return None
    lo, hi = _IV_LO, _IV_HI
    flo = price(S, K, T, r, lo, kind) - px
    fhi = price(S, K, T, r, hi, kind) - px
    if flo == 0:
        return lo
    if flo * fhi > 0:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        fmid = price(S, K, T, r, mid, kind) - px
        if abs(fmid) < 1e-8 or (hi - lo) < 1e-8:
            return mid
        if fmid > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def prob_above(S, X, T, r, s):
    """Risk-neutral lognormal P(S_T > X)."""
    if T <= 0 or s <= 0 or S <= 0 or X <= 0:
        return None
    d = (math.log(S / X) + (r - 0.5 * s * s) * T) / (s * math.sqrt(T))
    return norm_cdf(d)
