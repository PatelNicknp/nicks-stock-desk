/* RS line for the Chart Viewer: stock close divided by the SPY close, the same way the India desk
   draws it against the Nifty 50. No download: SPY comes from data/index_ohlc/SPY.csv, which the desk
   already saves. Weekly bars use the same Monday week as the chart's weekly candles and, like them,
   are dated on the last trading day of that week. A new 52-week high is strictly above the prior
   252 daily bars, or 52 weekly bars. "before" means that high in the line happened on a bar whose
   price did not make a new 52-week high. */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.rsLine = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const DAILY = 252;
  const WEEKLY = 52;
  const BENCHMARK = "SPY";

  function weekKey(iso) {
    const d = new Date(String(iso).slice(0, 10) + "T00:00:00Z");
    if (isNaN(d.getTime())) return "";
    d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
    return d.toISOString().slice(0, 10);
  }

  function num(v) {
    if (v == null || v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function sorted(bars) {
    return (bars || []).filter((b) => b && b.date).slice()
      .sort((a, b) => (String(a.date) < String(b.date) ? -1 : String(a.date) > String(b.date) ? 1 : 0));
  }

  // One point per Monday week, dated on its last trading day (the US weekly candle's date).
  function foldWeeks(bars) {
    const out = [];
    let cur = null;
    let key = "";
    sorted(bars).forEach((b) => {
      const day = String(b.date || "").slice(0, 10);
      const k = weekKey(day);
      if (!k) return;
      const c = num(b.c != null ? b.c : b.close);
      if (c == null) return;
      const h = num(b.h != null ? b.h : b.high);
      const high = h == null ? c : h;
      if (!cur || k !== key) {
        key = k;
        cur = { date: day, c: c, h: high, key: k };
        out.push(cur);
        return;
      }
      cur.h = Math.max(cur.h, high);
      cur.c = c;
      cur.date = day;
    });
    return out;
  }

  function dailyBars(bars) {
    const out = [];
    sorted(bars).forEach((b) => {
      const day = String(b.date || "").slice(0, 10);
      if (!day) return;
      const c = num(b.c != null ? b.c : b.close);
      if (c == null) return;
      const h = num(b.h != null ? b.h : b.high);
      out.push({ date: day, c: c, h: h == null ? c : h, key: day });
    });
    return out;
  }

  function maxOf(values, end, len) {
    let m = -Infinity;
    for (let i = end - len; i < end; i++) {
      if (values[i] > m) m = values[i];
    }
    return m;
  }

  function build(stockBars, benchBars, opts) {
    const weekly = !!(opts && opts.weekly);
    const lookback = weekly ? WEEKLY : DAILY;
    const stock = weekly ? foldWeeks(stockBars) : dailyBars(stockBars);
    const bench = weekly ? foldWeeks(benchBars) : dailyBars(benchBars);
    const benchClose = new Map();
    bench.forEach((b) => { benchClose.set(b.key, b.c); });
    const points = [];
    stock.forEach((b) => {
      const base = benchClose.get(b.key);
      if (!(base > 0)) return;
      points.push({ time: b.date, value: b.c / base, high: b.h });
    });
    const markers = [];
    const rs = points.map((p) => p.value);
    const px = points.map((p) => p.high);
    for (let i = lookback; i < points.length; i++) {
      if (!(points[i].value > maxOf(rs, i, lookback))) continue;
      const priceAlso = points[i].high > maxOf(px, i, lookback);
      markers.push({ time: points[i].time, kind: priceAlso ? "with" : "before" });
    }
    return { points: points, markers: markers, lookback: lookback };
  }

  return { build: build, weekKey: weekKey, DAILY: DAILY, WEEKLY: WEEKLY, BENCHMARK: BENCHMARK };
});
