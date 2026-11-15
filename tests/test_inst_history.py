"""13F fund-holder history (inst_history.py) and the CANSLIM I check that uses it.
Offline: synthetic SEC ZIPs and a fake OpenFIGI, no downloads."""
import io
import json
import os
import sys
import zipfile

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import inst_history as H  # noqa: E402
import setups  # noqa: E402
import test_canslim_strict as T  # noqa: E402

SUB_H = "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT"
COV_H = "ACCESSION_NUMBER\tREPORTCALENDARORQUARTER\tISAMENDMENT\tAMENDMENTNO\tAMENDMENTTYPE\tREPORTTYPE"
INF_H = "ACCESSION_NUMBER\tINFOTABLE_SK\tNAMEOFISSUER\tTITLEOFCLASS\tCUSIP\tFIGI\tVALUE\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL"


def _zip(subs, covs, infos):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SUBMISSION.tsv", "\n".join([SUB_H] + ["\t".join(r) for r in subs]) + "\n")
        zf.writestr("COVERPAGE.tsv", "\n".join([COV_H] + ["\t".join(r) for r in covs]) + "\n")
        zf.writestr("INFOTABLE.tsv", "\n".join([INF_H] + ["\t".join(r) for r in infos]) + "\n")
    buf.seek(0)
    return buf


def _info(acc, cusip, shares, typ="SH", putcall=""):
    return [acc, "1", "ACME INC", "COM", cusip, "", "100", str(shares), typ, putcall]


def _sample_zip():
    subs = [
        ["A1", "01-AUG-2026", "13F-HR", "0000000001", "30-JUN-2026"],
        ["A2", "02-AUG-2026", "13F-HR", "0000000002", "30-JUN-2026"],
        ["A3", "03-AUG-2026", "13F-HR", "0000000003", "30-JUN-2026"],
        ["A3R", "10-AUG-2026", "13F-HR/A", "0000000003", "30-JUN-2026"],   # restatement replaces A3
        ["A2N", "11-AUG-2026", "13F-HR/A", "0000000002", "30-JUN-2026"],   # new holdings adds to A2
        ["A4", "05-AUG-2026", "13F-NT", "0000000004", "30-JUN-2026"],      # notice, no holdings
        ["A5", "06-AUG-2026", "13F-HR", "0000000005", "31-MAR-2026"],      # late filer, older quarter
    ]
    covs = [
        ["A1", "30-JUN-2026", "", "", "", "13F HOLDINGS REPORT"],
        ["A2", "30-JUN-2026", "", "", "", "13F HOLDINGS REPORT"],
        ["A3", "30-JUN-2026", "", "", "", "13F HOLDINGS REPORT"],
        ["A3R", "30-JUN-2026", "Y", "1", "RESTATEMENT", "13F HOLDINGS REPORT"],
        ["A2N", "30-JUN-2026", "Y", "2", "NEW HOLDINGS", "13F HOLDINGS REPORT"],
        ["A4", "30-JUN-2026", "", "", "", "13F NOTICE"],
        ["A5", "31-MAR-2026", "", "", "", "13F HOLDINGS REPORT"],
    ]
    infos = [
        _info("A1", "000000AA1", 100), _info("A1", "000000AA1", 50),       # two lots, one filer
        _info("A1", "000000AA1", 999, putcall="Put"),                      # option, left out
        _info("A1", "000000BB2", 1000, typ="PRN"),                         # bond principal, left out
        _info("A2", "000000aa1", 10),                                      # lower case CUSIP
        _info("A2N", "000000BB2", 7),
        _info("A3", "000000AA1", 5000),                                    # replaced by the restatement
        _info("A3R", "000000AA1", 30),
        _info("A5", "000000AA1", 1),
    ]
    return _zip(subs, covs, infos)


def test_parse_zip_and_filing_choice():
    filings, pos = H.parse_zip(_sample_zip())
    assert set(filings["accession"]) == {"A1", "A2", "A3", "A3R", "A2N", "A5"}  # notice dropped
    kinds = dict(zip(filings["accession"], filings["kind"]))
    assert kinds["A2N"] == "add" and kinds["A3R"] == "base"
    assert dict(zip(filings["accession"], filings["period"]))["A5"] == "2026Q1"
    a1 = pos[(pos["accession"] == "A1")]
    assert list(a1["cusip"]) == ["000000AA1"] and float(a1["shares"].iloc[0]) == 150.0
    assert "000000AA1" in set(pos[pos["accession"] == "A2"]["cusip"])
    chosen = H.pick_filings(filings)
    assert set(chosen["accession"]) == {"A1", "A2", "A3R", "A2N", "A5"}
    counts = H.cusip_counts(filings, pos).set_index(["period", "cusip"])
    assert counts.loc[("2026Q2", "000000AA1"), "holders"] == 3
    assert counts.loc[("2026Q2", "000000AA1"), "shares"] == 150 + 10 + 30
    assert counts.loc[("2026Q2", "000000BB2"), "holders"] == 1  # from the NEW HOLDINGS amendment
    assert counts.loc[("2026Q1", "000000AA1"), "holders"] == 1


def test_new_holdings_amendment_before_the_base_is_ignored():
    f = pd.DataFrame([
        {"accession": "N", "cik": "9", "period": "2026Q2", "filing_date": pd.Timestamp("2026-07-01"), "kind": "add"},
        {"accession": "B", "cik": "9", "period": "2026Q2", "filing_date": pd.Timestamp("2026-08-01"), "kind": "base"},
    ])
    assert list(H.pick_filings(f)["accession"]) == ["B"]


def test_zip_names_listing_and_periods():
    s, e = H.zip_range("01jun2026-31aug2026_form13f.zip")
    assert (str(s.date()), str(e.date())) == ("2026-06-01", "2026-08-31")
    s, e = H.zip_range("2023q4_form13f.zip")
    assert (str(s.date()), str(e.date())) == ("2023-10-01", "2023-12-31")
    assert H.zip_range("readme.htm") is None
    html = ('<a href="/files/x/2023q4_form13f.zip">a</a><a href="/files/y/01jun2026-31aug2026_form13f.zip">b</a>'
            '<a href="/files/x/01mar2026-31may2026_form13f.zip">c</a><a href="/files/y/01jun2026-31aug2026_form13f.zip">dup</a>')
    lst = H.parse_listing(html)
    assert [r[1] for r in lst] == ["01jun2026-31aug2026_form13f.zip", "01mar2026-31may2026_form13f.zip", "2023q4_form13f.zip"]
    assert lst[0][0] == "https://www.sec.gov/files/y/01jun2026-31aug2026_form13f.zip"
    assert H.period_label(pd.Timestamp("2026-06-30")) == "2026Q2"
    assert str(H.period_end("2026Q1").date()) == "2026-03-31"
    rngs = [H.zip_range("01mar2026-31may2026_form13f.zip"), H.zip_range("01jun2026-31aug2026_form13f.zip")]
    # Q1 ends Mar 31: the Apr 1 to May 15 deadline window is inside the first ZIP.
    # Q2 ends Jun 30: Jul 1 to Aug 14 is inside the second. Q4 2025 starts Jan 1, not covered.
    assert H.complete_periods(rngs, ["2025Q4", "2026Q1", "2026Q2"]) == ["2026Q1", "2026Q2"]
    assert H.main_periods(rngs, ["2025Q4", "2026Q1", "2026Q2", "2026Q3"]) == ["2026Q1", "2026Q2"]
    # A ZIP that stops before the 45-day deadline leaves the quarter incomplete.
    short = [(pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-31"))]
    assert H.complete_periods(short, ["2026Q2"]) == []
    listing = [("u%d" % i, "n%d" % i, None, None) for i in range(8)]
    assert [r[1] for r in H.needed_zips(listing, {}, 6, force=True)] == ["n5", "n4", "n3", "n2", "n1", "n0"]
    assert [r[1] for r in H.needed_zips(listing, {}, 6)] == ["n1", "n0"]


def test_figi_ticker_pick():
    rows = [{"ticker": "BRK/B", "exchCode": "US", "securityType2": "Common Stock", "name": "BERKSHIRE"},
            {"ticker": "BRKB", "exchCode": "XX", "securityType2": "Common Stock"}]
    assert H.figi_ticker(rows) == ("BRK-B", "BERKSHIRE")
    assert H.figi_ticker(None) == ("", "")
    assert H.figi_ticker([{"ticker": "CSA", "exchCode": "GR", "securityType2": "Common Stock"}]) == ("", "")
    assert H.figi_ticker([{"ticker": "ACN", "exchCode": "UN", "securityType2": "Common Stock", "name": "ACCENTURE"}]) == ("ACN", "ACCENTURE")
    assert H.figi_job("G1151C101") == {"idType": "ID_CINS", "idValue": "G1151C101", "exchCode": "US"}
    assert H.figi_job("037833100", None) == {"idType": "ID_CUSIP", "idValue": "037833100"}


class _Resp:
    def __init__(self, code, payload=None, text=""):
        self.status_code = code
        self._p = payload
        self.text = text

    def json(self):
        return self._p


class _FakeFigi:
    def __init__(self, table, first_429=True):
        self.table = table
        self.calls = 0
        self.first_429 = first_429

    def post(self, url, json=None, timeout=None, headers=None):
        self.calls += 1
        if self.first_429 and self.calls == 1:
            return _Resp(429)
        out = []
        for job in json:
            t = self.table.get(job["idValue"])
            out.append({"data": [{"ticker": t, "exchCode": "US", "securityType2": "Common Stock", "name": t}]} if t
                       else {"warning": "No identifier found."})
        return _Resp(200, out)


def test_map_cusips_batches_retries_and_skips_known():
    fake = _FakeFigi({"C%d" % i: "T%d" % i for i in range(12)})
    rows = H.map_cusips(["C%d" % i for i in range(13)] + ["C0"], fake, known={"C12"}, sleep=lambda s: None, log=lambda *a: None)
    assert len(rows) == 12  # C12 already known, C0 asked once
    assert {r["cusip"]: r["ticker"] for r in rows}["C11"] == "T11"
    assert fake.calls == 3  # one 429 retry, then two batches of up to 10


def _write_universe_and_build(tmp_path, zips, table):
    data = tmp_path / "data"
    data.mkdir()
    paths = []
    for name, buf in zips:
        p = tmp_path / name
        p.write_bytes(buf.getvalue())
        paths.append(str(p))
    st = H.build(paths, ["ACME", "OTHER"], str(data), requests_mod=_FakeFigi(table, first_429=False), min_holders=1,
                 log=lambda *a: None)
    return data, st


def _quarter_zip(period_txt, filing_txt, holders_of_acme, prefix):
    subs, covs, infos = [], [], []
    for i in range(holders_of_acme):
        acc = "%s%d" % (prefix, i)
        subs.append([acc, filing_txt, "13F-HR", str(1000 + i), period_txt])
        covs.append([acc, period_txt, "", "", "", "13F HOLDINGS REPORT"])
        infos.append(_info(acc, "000000AA1", 100 + i))
    return _zip(subs, covs, infos)


def test_build_writes_compact_history_and_cusip_map(monkeypatch, tmp_path):
    monkeypatch.setattr(H.time, "sleep", lambda s: None)
    z1 = ("01mar2026-31may2026_form13f.zip", _quarter_zip("31-MAR-2026", "01-MAY-2026", 4, "Q1_"))
    z2 = ("01jun2026-31aug2026_form13f.zip", _quarter_zip("30-JUN-2026", "01-AUG-2026", 5, "Q2_"))
    data, st = _write_universe_and_build(tmp_path, [z1, z2], {"000000AA1": "ACME"})
    assert st["periods"] == ["2026Q1", "2026Q2"]
    hist = H.load_history(str(data))
    assert list(hist.columns) == H.HIST_COLS
    assert list(hist["holders"]) == [4, 5] and set(hist["complete"]) == {"yes"}
    assert list(hist["ticker"]) == ["ACME", "ACME"]
    cmap = H.load_cusip_map(str(data))
    assert list(cmap["ticker"]) == ["ACME"]
    sets = json.load(open(data / H.SETS_FILE))
    assert set(sets) == {z1[0], z2[0]}
    trend, info = H.holder_count_trend(hist, "ACME")
    assert trend == "up" and info["period_old"] == "2026Q1" and info["holders_new"] == 5
    # A later ZIP adds a quarter and keeps the older ones already on file.
    z3 = ("01sep2026-30nov2026_form13f.zip", _quarter_zip("30-SEP-2026", "01-NOV-2026", 5, "Q3_"))
    p3 = tmp_path / z3[0]
    p3.write_bytes(z3[1].getvalue())
    H.build([str(p3)], ["ACME"], str(data), requests_mod=_FakeFigi({}, first_429=False), log=lambda *a: None)
    hist = H.load_history(str(data))
    assert list(hist["period"]) == ["2026Q1", "2026Q2", "2026Q3"]
    assert H.holder_count_trend(hist, "ACME")[0] == "flat"


def _hist(rows):
    return pd.DataFrame([{"ticker": t, "period": p, "holders": h, "shares": h * 10, "cusips": "X", "complete": c}
                         for t, p, h, c in rows], columns=H.HIST_COLS)


def test_holder_count_trend_rules():
    h = _hist([
        ("UP", "2026Q1", 100, "yes"), ("UP", "2026Q2", 110, "yes"),
        ("FLAT", "2026Q1", 100, "yes"), ("FLAT", "2026Q2", 100, "yes"),
        ("TOL", "2026Q1", 100, "yes"), ("TOL", "2026Q2", 99, "yes"),
        ("DOWN", "2026Q1", 100, "yes"), ("DOWN", "2026Q2", 90, "yes"),
        ("ONE", "2026Q2", 100, "yes"),
        ("GAP", "2025Q4", 100, "yes"), ("GAP", "2026Q2", 50, "yes"),
        ("PART", "2026Q1", 100, "yes"), ("PART", "2026Q2", 120, "yes"), ("PART", "2026Q3", 10, "no"),
    ])
    assert H.holder_count_trend(h, "UP")[0] == "up"
    assert H.holder_count_trend(h, "FLAT")[0] == "flat"
    assert H.holder_count_trend(h, "TOL")[0] == "flat"
    assert H.holder_count_trend(h, "TOL", tolerance_pct=0)[0] == "down"
    assert H.holder_count_trend(h, "DOWN")[0] == "down"
    assert H.holder_count_trend(h, "ONE")[0] == ""
    assert H.holder_count_trend(h, "GAP")[0] == ""  # quarters not back to back
    assert H.holder_count_trend(h, "PART")[0] == "up"  # incomplete newest quarter is skipped
    assert H.holder_count_trend(h, "NONE")[0] == ""
    assert H.holder_count_trend(None, "UP")[0] == ""
    j = _hist([("CUSIP", "2026Q1", 30, "yes"), ("CUSIP", "2026Q2", 900, "yes"),
               ("GONE", "2026Q1", 900, "yes"), ("GONE", "2026Q2", 40, "yes")])
    t, info = H.holder_count_trend(j, "CUSIP")
    assert t == "" and info["reason"] == "jump" and info["holders_new"] == 900
    assert H.holder_count_trend(j, "GONE")[0] == ""
    assert H.holder_count_trend(j, "GONE", max_jump_pct=None)[0] == "down"
    assert H.holder_count_trend(h, "ONE")[1]["reason"] == "quarters"


def _run_i(inst_hist, holders=None, cfg=None):
    stocks = {n: T._named(n, T._stock()) for n in ("UP", "FLAT", "DOWN", "NOI")}
    frames = {t: T._ohlc(c, v) for t, (c, v, _q, _a) in stocks.items()}
    frames["SPY"] = T._ohlc(T._spy(), T._flat_vol(1e8))
    close = pd.DataFrame({t: f["close"] for t, f in frames.items()})
    high = pd.DataFrame({t: f["high"] for t, f in frames.items()})
    low = pd.DataFrame({t: f["low"] for t, f in frames.items()})
    vol = pd.DataFrame({t: f["volume"] for t, f in frames.items()})
    q = pd.DataFrame([r for (_c, _v, qq, _a) in stocks.values() for r in qq])
    a = pd.DataFrame([r for (_c, _v, _q, aa) in stocks.values() for r in aa])
    uni = pd.DataFrame([{"ticker": t, "company": t, "sector": "Industrials", "index_membership": "SP500"} for t in stocks])
    hold = pd.DataFrame(holders or [], columns=["ticker", "inst_up", "inst_down", "ownership_pct"])
    out, _m = setups.scan_canslim(close, high, low, vol, uni, q, a, hold, rs_map={t: 90 for t in stocks}, cfg=cfg,
                                  inst_hist=inst_hist)
    return out


H13 = _hist([
    ("UP", "2026Q1", 100, "yes"), ("UP", "2026Q2", 120, "yes"),
    ("FLAT", "2026Q1", 100, "yes"), ("FLAT", "2026Q2", 99, "yes"),
    ("DOWN", "2026Q1", 100, "yes"), ("DOWN", "2026Q2", 80, "yes"),
])
NASDAQ = [{"ticker": "DOWN", "inst_up": 10, "inst_down": 1, "ownership_pct": 50},   # Nasdaq says buying
          {"ticker": "UP", "inst_up": 1, "inst_down": 10, "ownership_pct": 50}]     # Nasdaq says selling


def test_canslim_i_uses_13f_holder_count_trend():
    out = _run_i(H13, holders=NASDAQ)
    assert T._tickers(out) == {"UP", "FLAT", "NOI"}
    by = out.set_index("ticker")
    assert by.loc["UP", "i_trend"] == "up" and "120 in 2026Q2 versus 100 in 2026Q1" in by.loc["UP", "i_status"]
    assert by.loc["FLAT", "i_trend"] == "flat" and "counts as flat" in by.loc["FLAT", "i_status"]
    assert by.loc["NOI", "i_trend"] == "not verified"
    assert "does not fail" in by.loc["NOI", "i_status"] and "I not verified" in by.loc["NOI", "note"]
    for col in T.OLD_COLS:
        if col != "disclaimer":
            assert col in out.columns


def test_canslim_i_big_jump_is_not_verified_not_a_fail():
    jump = pd.concat([H13, _hist([("NOI", "2026Q1", 900, "yes"), ("NOI", "2026Q2", 40, "yes")])], ignore_index=True)
    out = _run_i(jump)
    by = out.set_index("ticker")
    assert "NOI" in by.index and by.loc["NOI", "i_trend"] == "not verified"
    assert "CUSIP changed" in by.loc["NOI", "i_status"]
    strict = _run_i(jump, cfg={"canslim": {"i_max_jump_pct": 1000}})
    assert "NOI" not in T._tickers(strict)


def test_canslim_i_tolerance_from_config():
    out = _run_i(H13, cfg={"canslim": {"i_flat_tolerance_pct": 0}})
    assert T._tickers(out) == {"UP", "NOI"}


def test_canslim_i_switch_off_or_no_history_uses_nasdaq_check():
    off = _run_i(H13, holders=NASDAQ, cfg={"features": {"canslim_i_13f_trend": False}})
    assert T._tickers(off) == {"DOWN", "FLAT", "NOI"}
    none = _run_i(None, holders=NASDAQ)
    assert T._tickers(none) == {"DOWN", "FLAT", "NOI"}


def test_build_setups_passes_inst_hist():
    stocks = {"DOWN": T._named("DOWN", T._stock())}
    frames = {t: T._ohlc(c, v) for t, (c, v, _q, _a) in stocks.items()}
    frames["SPY"] = T._ohlc(T._spy(), T._flat_vol(1e8))
    close = pd.DataFrame({t: f["close"] for t, f in frames.items()})
    vol = pd.DataFrame({t: f["volume"] for t, f in frames.items()})
    q = pd.DataFrame(stocks["DOWN"][2])
    a = pd.DataFrame(stocks["DOWN"][3])
    uni = pd.DataFrame([{"ticker": "DOWN", "company": "D", "sector": "Industrials", "index_membership": "SP500"}])
    feats = {"scanner_canslim": True}
    for k in ("scanner_vcp", "scanner_box", "scanner_flag", "scanner_leaders", "scanner_52w", "scanner_breakdown",
              "scanner_volume", "scanner_qullamaggie", "scanner_marios", "scorecard_canslim"):
        feats[k] = False
    on = setups.build_setups(close, close, close, vol, uni, q, a, pd.DataFrame(), feats, rs_map={"DOWN": 90}, inst_hist=H13)
    off = setups.build_setups(close, close, close, vol, uni, q, a, pd.DataFrame(), feats, rs_map={"DOWN": 90})
    assert len(on["scanner_canslim"]) == 0
    assert list(off["scanner_canslim"]["ticker"]) == ["DOWN"]


class _FakeSec:
    def __init__(self, html, fail=False):
        self.html = html
        self.fail = fail
        self.urls = []

    def get(self, url, headers=None, timeout=None, stream=False):
        self.urls.append((url, headers))
        if self.fail:
            raise RuntimeError("network down")
        return _Resp(200, text=self.html)


def test_update_history_skips_when_current_and_never_raises(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    H.save_sets(str(data), {"01jun2026-31aug2026_form13f.zip": {"start": "2026-06-01", "end": "2026-08-31"}})
    html = '<a href="/files/x/01jun2026-31aug2026_form13f.zip">x</a>'
    sec = _FakeSec(html)
    cfg = {"rate_limits": {"sec_user_agent": "Desk test me@example.com"}}
    msg = H.update_history(cfg, str(tmp_path), sec, ["ACME"])
    assert "current" in msg and len(sec.urls) == 1
    assert sec.urls[0][1]["User-Agent"] == "Desk test me@example.com"
    bad = H.update_history(cfg, str(tmp_path), _FakeSec(html, fail=True), ["ACME"])
    assert "failed" in bad
    assert not (data / H.HISTORY_FILE).exists()


def test_config_switches_and_notes():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    assert cfg["features"]["canslim_i_13f_trend"] is True
    assert cfg["features"]["inst_13f_history"] is True
    assert cfg["canslim"]["i_flat_tolerance_pct"] == 2
    assert cfg["canslim"]["i_max_jump_pct"] == 50
    assert "inst_13f_history.csv" in cfg["canslim"]["_note"]
    assert setups.canslim_i_13f_on({"features": {"canslim_i_13f_trend": False}}) is False
    assert setups.canslim_i_13f_on({}) is True


def test_stored_history_is_compact_and_has_no_prices():
    path = os.path.join(ROOT, "data", H.HISTORY_FILE)
    if not os.path.exists(path):
        pytest.skip("history not built")
    hist = pd.read_csv(path)
    assert list(hist.columns) == H.HIST_COLS
    assert os.path.getsize(path) < 2_000_000
    uni = set(pd.read_csv(os.path.join(ROOT, "data", "universe.csv"))["ticker"])
    assert set(hist["ticker"]) <= uni


class _UsOnlyFigi(_FakeFigi):
    """Answers a CINS id only when asked without exchCode=US, like OpenFIGI does."""

    def post(self, url, json=None, timeout=None, headers=None):
        self.calls += 1
        out = []
        for job in json:
            t = self.table.get(job["idValue"])
            if t and job["idType"] == "ID_CINS" and "exchCode" in job:
                t = None
            out.append({"data": [{"ticker": t, "exchCode": "UN", "securityType2": "Common Stock", "name": t}]} if t
                       else {"warning": "No identifier found."})
        return _Resp(200, out)


def test_build_second_pass_maps_non_us_issuers(monkeypatch, tmp_path):
    monkeypatch.setattr(H.time, "sleep", lambda s: None)
    subs, covs, infos = [], [], []
    for i in range(3):
        acc = "G%d" % i
        subs.append([acc, "01-AUG-2026", "13F-HR", str(50 + i), "30-JUN-2026"])
        covs.append([acc, "30-JUN-2026", "", "", "", "13F HOLDINGS REPORT"])
        infos.append(_info(acc, "G1151C101", 10))
    p = tmp_path / "01jun2026-31aug2026_form13f.zip"
    p.write_bytes(_zip(subs, covs, infos).getvalue())
    data = tmp_path / "data"
    data.mkdir()
    fake = _UsOnlyFigi({"G1151C101": "ACN"})
    H.build([str(p)], ["ACN"], str(data), requests_mod=fake, min_holders=1, log=lambda *a: None)
    cmap = H.load_cusip_map(str(data))
    assert cmap.set_index("cusip").loc["G1151C101", "ticker"] == "ACN"
    assert cmap.set_index("cusip").loc["G1151C101", "source"] == "openfigi2"
    assert list(H.load_history(str(data))["holders"]) == [3]
    # A rebuild does not ask again.
    calls = fake.calls
    H.build([str(p)], ["ACN"], str(data), requests_mod=fake, min_holders=1, log=lambda *a: None)
    assert fake.calls == calls


def test_name_key():
    assert H.name_key("Exxon Mobil Corp") == H.name_key("EXXONMOBIL HOLDINGS CORP COM SHS") == "EXXONMOBIL"
    assert H.name_key("TEVA PHARMACEUTICAL INDS LTD") == H.name_key("TEVA PHARMACEUTICAL INDUSTRIES LTD")
    assert H.name_key("") == ""


def _cmap(rows):
    return pd.DataFrame(rows, columns=H.MAP_COLS)


def _counts(rows):
    return pd.DataFrame(rows, columns=["period", "cusip", "holders", "shares"])


def _names(rows):
    return pd.DataFrame(rows, columns=["cusip", "name", "rows"])


def test_continuity_ties_retired_cusips_and_skips_the_rest():
    cmap = _cmap([
        ["30233Q108", "XOM", "EXXONMOBIL HOLDINGS", "openfigi"],
        ["30231G102", "", "", "openfigi2"],      # retired Exxon CUSIP, same name
        ["438516205", "HON", "HONEYWELL", "openfigi"],
        ["438516106", "", "", "openfigi2"],      # old Honeywell, same issuer code
        ["438516AB2", "", "", "openfigi2"],      # Honeywell bond: letters in the issue number
        ["438516304", "", "", "openfigi2"],      # small side issue
        ["02079K305", "GOOG", "ALPHABET", "openfigi"],
        ["02079K999", "", "", "openfigi2"],      # live next to GOOG every quarter
    ])
    q = ["2026Q1", "2026Q2", "2026Q3"]
    counts = _counts(
        [[p, "30231G102", 4000, 1] for p in q] + [["2026Q3", "30233Q108", 400, 1]]
        + [[p, "438516205", 2500, 1] for p in q] + [["2026Q1", "438516106", 2400, 1]]
        + [[p, "438516AB2", 900, 1] for p in q] + [[p, "438516304", 30, 1] for p in q]
        + [[p, "02079K305", 4000, 1] for p in q] + [[p, "02079K999", 3000, 1] for p in q])
    names = _names([["30231G102", "EXXON MOBIL CORP", 100], ["30233Q108", "EXXONMOBIL HOLDINGS CORP COM SHS", 50],
                    ["438516205", "HONEYWELL INTL INC", 10], ["438516106", "HONEYWELL INTL INC", 10],
                    ["438516AB2", "HONEYWELL INTL INC", 10], ["02079K999", "ALPHABET INC", 10],
                    ["02079K305", "ALPHABET INC", 10]])
    out = {r["cusip"]: r["ticker"] for r in H.continuity_map(counts, names, cmap, ["XOM", "HON", "GOOG"])}
    assert out == {"30231G102": "XOM", "438516106": "HON"}


def test_company_fallback_only_for_names_with_no_cusip():
    cmap = _cmap([["682680103", "", "", "openfigi2"], ["74736K101", "", "", "openfigi2"],
                  ["111111101", "", "", "openfigi2"], ["037833100", "AAPL", "APPLE", "openfigi"],
                  ["222222101", "", "", "openfigi2"]])
    counts = _counts([["2026Q2", c, 500, 1] for c in ("682680103", "74736K101", "111111101", "222222101")])
    names = _names([["682680103", "ONEOK INC NEW", 10], ["74736K101", "QORVO INC", 10],
                    ["111111101", "SOMETHING ELSE INC", 10], ["222222101", "APPLE INC", 10]])
    out = {r["cusip"]: r["ticker"] for r in H.company_fallback(counts, names, cmap,
                                                               {"OKE": "Oneok", "QRVO": "Qorvo", "AAPL": "Apple Inc."})}
    assert out == {"682680103": "OKE", "74736K101": "QRVO"}  # AAPL already has its CUSIP
