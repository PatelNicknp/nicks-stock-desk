"""Price check for a debit spread.

Fair value keeps each leg's smile: model vol times (leg IV / ATM IV).
The blend is 35% 20-day realized, 35% 60-day realized, and 30% ATM implied.
The label is the market debit divided by that blend fair value:
CHEAP under 0.9, FAIR from 0.9 through 1.2, OVERPAYING above 1.2.
The score is the mentor's buyer score, 50 minus 200 times (price/fair - 1),
clamped to 0..100. A high score means the debit is cheap versus the blend.
"""
from options.bs import price as bs_price

BLEND_W = (0.35, 0.35, 0.30)


def buyer_score(ratio):
    if ratio is None:
        return None
    raw = 50.0 - 200.0 * (ratio - 1.0)
    return int(max(0, min(100, round(raw))))


def label_for(ratio):
    if ratio is None:
        return ""
    if ratio < 0.9:
        return "CHEAP"
    if ratio <= 1.2:
        return "FAIR"
    return "OVERPAYING"


def price_check(legs, S, T, r, debit, atm, rv20, rv60):
    """legs is a list of (sign, strike, kind, iv). Sign +1 long, -1 short.

    Returns None when no fair value can be built. Otherwise a dict with
    label, score, ratio, fair, blend, iv_rv20, iv_rv60.
    """
    if debit is None or debit <= 0 or atm is None or atm <= 0 or T <= 0:
        return None
    vols = {}
    if rv20:
        vols["RV20"] = rv20
    if rv60:
        vols["RV60"] = rv60
    if rv20 and rv60:
        vols["Blend"] = BLEND_W[0] * rv20 + BLEND_W[1] * rv60 + BLEND_W[2] * atm
    elif vols:
        vols["Blend"] = 0.6 * list(vols.values())[0] + 0.4 * atm
    if "Blend" not in vols or vols["Blend"] <= 0:
        return None

    def fair_at(volm):
        total = 0.0
        for sgn, strike, kind, iv in legs:
            smile = (iv / atm) if atm else 1.0
            lv = max(volm * smile, 0.01)
            total += sgn * bs_price(S, strike, T, r, lv, kind)
        return abs(total)

    fair = {k: fair_at(v) for k, v in vols.items()}
    mid_f = fair["Blend"]
    if mid_f <= 1e-6:
        return None
    ratio = debit / mid_f
    ivs = [iv for _, _, _, iv in legs if iv]
    ivm = sum(ivs) / len(ivs) if ivs else atm
    return {
        "label": label_for(ratio),
        "score": buyer_score(ratio),
        "ratio": ratio,
        "fair": mid_f,
        "fair_by": fair,
        "blend": vols["Blend"],
        "iv": ivm,
        "iv_rv20": (ivm / rv20) if rv20 else None,
        "iv_rv60": (ivm / rv60) if rv60 else None,
    }
