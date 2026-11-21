"""Composite Rating: the formula, blanks, weights from config, the scores.csv column, and the main run wiring."""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import composite  # noqa: E402
import stock_desk  # noqa: E402
import tables  # noqa: E402


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _scores(n=200, seed=1):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "ticker": ["T%03d" % i for i in range(n)],
        "rs": rng.integers(1, 100, n).astype(float),
        "eps_rating": rng.integers(1, 100, n).astype(float),
        "dist_52w_high_pct": -rng.uniform(0, 60, n),
        "rev_growth": rng.uniform(-20, 80, n),
        "roe": rng.uniform(-10, 40, n),
    })


def test_ratings_are_1_to_99_and_spread_across_the_desk():
    comp = composite.composite_ratings(_scores())
    assert comp.min() == 1 and comp.max() == 99
    assert abs(comp.mean() - 50) < 3
    assert ((comp >= 80).mean() > 0.15) and ((comp >= 80).mean() < 0.30)
    assert comp.notna().all()


def test_a_stock_better_on_every_piece_rates_higher():
    s = _scores()
    s.loc[0, ["rs", "eps_rating", "dist_52w_high_pct", "rev_growth", "roe"]] = [99, 99, -0.5, 70, 38]
    s.loc[1, ["rs", "eps_rating", "dist_52w_high_pct", "rev_growth", "roe"]] = [5, 5, -55, -15, -8]
    comp = composite.composite_ratings(s)
    assert comp[0] >= 97 and comp[1] <= 3


def test_missing_pieces_are_left_out_not_zero_and_thin_stocks_are_blank():
    s = _scores()
    s.loc[2, "eps_rating"] = np.nan
    s.loc[3, "rs"] = np.nan
    s.loc[4, ["eps_rating", "dist_52w_high_pct", "rev_growth", "roe"]] = np.nan  # only RS left
    s.loc[5, "eps_rating"] = 0  # 0 is not a rating
    comp = composite.composite_ratings(s)
    assert pd.notna(comp[2]) and comp[2] >= 1
    assert pd.isna(comp[3])      # the RS Rating is required
    assert pd.isna(comp[4])      # fewer than min_parts pieces
    assert pd.notna(comp[5])     # EPS dropped, the other pieces still rate it
    assert (comp.dropna() >= 1).all()


def test_weights_and_min_parts_come_from_config():
    s = _scores()
    rs_only = {"composite": {"w_eps": 0, "w_rs": 1, "w_high": 0, "w_sales": 0, "w_margin": 0, "min_parts": 1}}
    comp = composite.composite_ratings(s, cfg=rs_only)
    assert comp.corr(s["rs"]) > 0.99
    cfg = json.loads(_read("config.json"))
    got = composite.settings(cfg)
    assert (got["w_eps"], got["w_rs"], got["w_high"], got["w_sales"], got["w_margin"], got["min_parts"]) == (0.3, 0.3, 0.15, 0.15, 0.1, 3)
    assert abs(sum(got[k] for k in ("w_eps", "w_rs", "w_high", "w_sales", "w_margin")) - 1.0) < 1e-9


def test_sales_and_margin_come_from_saved_quarters_and_fall_back_to_yearly():
    rows = []
    for t, grow, margin in (("GROW", 1.5, 0.30), ("SLOW", 1.0, 0.02)):
        for k, f in enumerate(["CY2025Q1", "CY2025Q2", "CY2025Q3", "CY2025Q4", "CY2026Q1", "CY2026Q2"]):
            rev = 100.0 * (grow if k >= 4 else 1.0)
            rows.append({"ticker": t, "frame": f, "revenue": rev, "net_income": rev * margin})
    fin = composite.fundamentals_inputs(pd.DataFrame(rows)).set_index("ticker")
    assert abs(fin.loc["GROW", "sales_growth"] - 50) < 1e-6 and abs(fin.loc["SLOW", "sales_growth"]) < 1e-6
    assert fin.loc["GROW", "net_margin"] > fin.loc["SLOW", "net_margin"]
    assert len(composite.fundamentals_inputs(None)) == 0


def test_attach_writes_blank_not_zero_and_leaves_the_input_alone():
    s = _scores(30)
    s.loc[0, "rs"] = np.nan
    out = composite.attach(s)
    assert "composite_rating" not in s.columns
    assert out.loc[0, "composite_rating"] == ""
    assert all(isinstance(v, int) and 1 <= v <= 99 for v in out["composite_rating"].iloc[1:])
    assert len(composite.attach(pd.DataFrame())) == 0


def test_scores_table_has_composite_after_eps_rating():
    cols = tables.COLS["scores"]
    assert cols.count("composite_rating") == 1 and cols.index("composite_rating") == cols.index("eps_rating") + 1
    assert cols[-3:] == ["data_status", "note", "disclaimer"]


def test_main_run_and_export_write_the_composite_with_a_switch():
    src = _read("stock_desk.py")
    assert 'if features.get("composite_rating", True):' in src
    assert "scores = composite.attach(scores, quarters, cfg)" in src
    assert 'if (cfg or {}).get("features", {}).get("composite_rating", True):' in src
    assert "scores = composite.attach(scores, read_csv(os.path.join(cache_dir, \"quarters.csv\")), cfg)" in src
    assert '"base_patterns": base_patterns.export_frame(bases, features.get("base_patterns", True))' in src
    cfg = json.loads(_read("config.json"))
    assert cfg["features"]["composite_rating"] is True and cfg["features"]["base_patterns"] is True


def test_latest_data_ratings_are_sane_when_scores_has_them():
    path = os.path.join(ROOT, "data", "scores.csv")
    s = pd.read_csv(path)
    q = pd.read_csv(os.path.join(ROOT, "cache", "quarters.csv"))
    comp = composite.composite_ratings(s, q, json.loads(_read("config.json")))
    assert comp.notna().sum() > 1500 and comp.min() >= 1 and comp.max() <= 99
    assert 0.12 < (comp >= 80).sum() / comp.notna().sum() < 0.30


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("composite tests ok")
