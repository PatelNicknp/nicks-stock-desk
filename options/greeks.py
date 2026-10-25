"""Black-Scholes Greeks, no dividends.

Theta is per calendar day. Vega is per 1 vol point. Rho is per 1 rate point.
Values are per share.
"""
import math

from options.bs import norm_cdf, norm_pdf


def greeks(S, K, T, r, s, kind):
    T = max(float(T), 1.0 / 365.0 / 24.0)
    s = max(float(s), 1e-4)
    sq = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * s * s) * T) / (s * sq)
    d2 = d1 - s * sq
    n1 = norm_pdf(d1)
    disc = math.exp(-r * T)
    if kind == "call":
        delta = norm_cdf(d1)
        price = S * delta - K * disc * norm_cdf(d2)
        theta = (-S * n1 * s / (2.0 * sq) - r * K * disc * norm_cdf(d2)) / 365.0
        rho = K * T * disc * norm_cdf(d2) / 100.0
    else:
        delta = norm_cdf(d1) - 1.0
        price = K * disc * norm_cdf(-d2) - S * norm_cdf(-d1)
        theta = (-S * n1 * s / (2.0 * sq) + r * K * disc * norm_cdf(-d2)) / 365.0
        rho = -K * T * disc * norm_cdf(-d2) / 100.0
    gamma = n1 / (S * s * sq)
    vega = S * n1 * sq / 100.0
    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "rho": rho,
    }
