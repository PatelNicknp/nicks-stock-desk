"""Nasdaq-100 joins the S&P 500 and the growth list without duplicate rows."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import stock_desk as desk


def _frame(rows, flag):
    df = pd.DataFrame(rows)
    return desk.wiki_constituents([df], flag) if False else desk._blank_flags(pd.DataFrame(rows), flag)


def test_membership_order_and_dedupe():
    sp = _frame([
        {"ticker": "AAPL", "company": "Apple", "sector": "Information Technology"},
        {"ticker": "JPM", "company": "JPMorgan", "sector": "Financials"},
    ], "in_sp500")
    ndx = _frame([
        {"ticker": "AAPL", "company": "Apple Inc.", "sector": "Technology"},
        {"ticker": "MELI", "company": "MercadoLibre", "sector": "Consumer Discretionary"},
    ], "in_ndx100")
    growth = desk.growth_frame({"growth_names": ["MELI", "ZZZ"]})
    out = desk.combine_indexes([sp, ndx, growth], ["COST"], [], {"sp500": True, "ndx100": True, "growth": True})
    assert list(out["ticker"]).count("AAPL") == 1
    assert list(out["ticker"]).count("MELI") == 1
    aapl = out[out.ticker == "AAPL"].iloc[0]
    assert aapl["index_membership"] == "SP500 / NDX100"
    assert aapl["sector"] == "Information Technology"  # S&P sector wins when both exist
    meli = out[out.ticker == "MELI"].iloc[0]
    assert meli["index_membership"] == "NDX100 / Growth"
    assert meli["in_sp500"] == "no"
    zzz = out[out.ticker == "ZZZ"].iloc[0]
    assert zzz["index_membership"] == "Growth"
    cost = out[out.ticker == "COST"].iloc[0]
    assert cost["index_membership"] == "Focus"
    assert len(out) == 5


def test_switch_drops_only_that_list():
    sp = _frame([{"ticker": "JPM", "company": "JPMorgan", "sector": "Financials"}], "in_sp500")
    ndx = _frame([
        {"ticker": "JPM", "company": "JPMorgan", "sector": "Financials"},
        {"ticker": "MELI", "company": "MercadoLibre", "sector": "Consumer Discretionary"},
    ], "in_ndx100")
    growth = desk.growth_frame({"growth_names": ["ZZZ"]})
    off = desk.combine_indexes([sp, ndx, growth], [], [], {"sp500": True, "ndx100": False, "growth": False})
    assert set(off["ticker"]) == {"JPM"}
    assert off.iloc[0]["index_membership"] == "SP500 / NDX100"
    only_growth = desk.combine_indexes([sp, ndx, growth], [], [], {"sp500": False, "ndx100": False, "growth": True})
    assert set(only_growth["ticker"]) == {"ZZZ"}
    held = desk.combine_indexes([sp, ndx, growth], ["MELI"], [], {"sp500": False, "ndx100": False, "growth": False})
    assert set(held["ticker"]) == {"MELI"}
    assert held.iloc[0]["index_membership"] == "NDX100"


def test_wiki_tables_for_both_indexes():
    extra = ["T%02d" % i for i in range(20)]
    sp = pd.DataFrame({
        "Symbol": ["BRK.B", "AAPL", "BAD TICKER"] + extra,
        "Security": ["Berkshire [1]", "Apple", "Nope"] + extra,
        "GICS Sector": ["Financials", "Information Technology", "Energy"] + ["Industrials"] * 20,
    })
    # too-small tables and a ticker-style Nasdaq table
    tiny = pd.DataFrame({"Ticker": ["A"], "Company": ["x"], "ICB Industry": ["Technology"]})
    ndx = pd.DataFrame({
        "Ticker": ["AMD", "GOOG", "MSFT[2]"] + extra,
        "Company": ["Advanced Micro Devices", "Alphabet", "Microsoft"] + extra,
        "ICB Industry[1]": ["Technology"] * 23,
    })
    sp_out = desk.wiki_constituents([tiny, sp], "in_sp500")
    assert {"BRK-B", "AAPL"} <= set(sp_out["ticker"])
    assert "BAD TICKER" not in set(sp_out["ticker"])
    assert (sp_out["in_sp500"] == "yes").all()
    assert (sp_out["in_ndx100"] == "no").all()
    assert sp_out.loc[sp_out.ticker == "BRK-B", "company"].iloc[0] == "Berkshire"
    ndx_out = desk.wiki_constituents([tiny, ndx], "in_ndx100")
    assert {"AMD", "GOOG", "MSFT"} <= set(ndx_out["ticker"])
    assert (ndx_out["sector"] == "Information Technology").all()
    assert (ndx_out["in_ndx100"] == "yes").all()


def test_switches_default_on():
    assert desk.index_switches({}) == {"sp500": True, "ndx100": True, "growth": True}
    assert desk.index_switches({"indexes": {"ndx100": False}})["ndx100"] is False
    assert desk.membership_label("yes", "yes", "yes") == "SP500 / NDX100 / Growth"
    assert desk.membership_label("no", "no", "no") == "Focus"


if __name__ == "__main__":
    test_membership_order_and_dedupe()
    test_switch_drops_only_that_list()
    test_wiki_tables_for_both_indexes()
    test_switches_default_on()
    print("universe ok")
