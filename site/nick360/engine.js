/* Nick 360 calculations. Our definitions, computed from bars the caller already has.
   No network. No third-party rating. A missing input stays missing. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.N360 = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const MA_PERIODS = [10, 20, 50, 150, 200];
  const MA_COLORS = { 10: "#22c55e", 20: "#f97316", 50: "#3b82f6", 150: "#eab308", 200: "#ef4444" };
  const ENTRY_COLOR = "#F59E0B";
  const STOP_COLOR = "#EF4444";
  const TARGET_COLOR = "#22C55E";
  const PIVOT_COLOR = "#a5b4fc";
  const GRADE_ORDER = { A: 4, B: 3, C: 2, D: 1 };
  const RS_WEIGHTS = [
    [63, 0.4],
    [126, 0.2],
    [189, 0.2],
    [252, 0.2],
  ];

  function finite(n) {
    return typeof n === "number" && Number.isFinite(n);
  }
  function pos(n) {
    return finite(n) && n > 0;
  }
  function clamp(n, lo, hi) {
    return Math.max(lo, Math.min(hi, n));
  }
  function round(n, d) {
    if (!finite(n)) return null;
    const p = Math.pow(10, d);
    return Math.round(n * p) / p;
  }
  function mean(xs) {
    if (!xs.length) return null;
    let s = 0;
    for (let i = 0; i < xs.length; i++) s += xs[i];
    return s / xs.length;
  }

  function parseBars(rows) {
    const dropped = [];
    const raw = [];
    (rows || []).forEach((r, idx) => {
      const d = String(r.d || r.date || "").slice(0, 10);
      const c = Number(r.c != null ? r.c : r.close);
      if (!d || !pos(c)) {
        dropped.push(idx);
        return;
      }
      let o = Number(r.o != null ? r.o : r.open);
      let h = Number(r.h != null ? r.h : r.high);
      let l = Number(r.l != null ? r.l : r.low);
      const v0 = r.v != null ? r.v : r.volume;
      const v = v0 == null || v0 === "" ? null : Number(v0);
      if (!pos(o)) o = c;
      if (!pos(h)) h = Math.max(o, c);
      if (!pos(l)) l = Math.min(o, c);
      if (h < l) {
        h = Math.max(o, c);
        l = Math.min(o, c);
      }
      h = Math.max(h, o, c);
      l = Math.min(l, o, c);
      raw.push({ d: d, o: o, h: h, l: l, c: c, v: finite(v) && v >= 0 ? v : null });
    });
    raw.sort((a, b) => (a.d < b.d ? -1 : a.d > b.d ? 1 : 0));
    const bars = [];
    raw.forEach((b) => {
      if (bars.length && bars[bars.length - 1].d === b.d) bars[bars.length - 1] = b;
      else bars.push(b);
    });
    return { bars: bars, dropped: dropped.length };
  }

  function smaSeries(values, n) {
    const out = new Array(values.length).fill(null);
    let sum = 0;
    let filled = 0;
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (!pos(v)) {
        sum = 0;
        filled = 0;
        continue;
      }
      sum += v;
      filled += 1;
      if (filled > n) {
        const old = values[i - n];
        if (!pos(old)) {
          sum = 0;
          filled = 0;
          continue;
        }
        sum -= old;
        filled -= 1;
      }
      if (filled === n) out[i] = sum / n;
    }
    return out;
  }

  function windowMean(bars, i, fromBack, toBack, field) {
    if (i - fromBack < 0) return null;
    let sum = 0;
    const count = fromBack - toBack + 1;
    for (let k = i - fromBack; k <= i - toBack; k++) {
      const v = bars[k][field];
      if (!finite(v)) return null;
      sum += v;
    }
    if (count <= 0) return null;
    return sum / count;
  }

  function analyzeBars(bars) {
    const n = bars.length;
    const closes = bars.map((b) => b.c);
    const sma = {};
    MA_PERIODS.forEach((p) => { sma[p] = smaSeries(closes, p); });
    const relVol = new Array(n).fill(null);
    const dry = new Array(n).fill(null);
    const pressure = new Array(n).fill(null);
    const risk = new Array(n).fill(null);
    const wscore = new Array(n).fill(null);
    const rank = new Array(n).fill(null);
    const grade = new Array(n).fill(null);
    for (let i = 0; i < n; i++) {
      const base50 = windowMean(bars, i, 50, 1, "v");
      if (base50 != null && base50 > 0 && finite(bars[i].v)) relVol[i] = bars[i].v / base50;
      const recent = windowMean(bars, i, 9, 0, "v");
      const prior = windowMean(bars, i, 59, 10, "v");
      if (recent != null && prior != null && prior > 0) dry[i] = recent / prior;
      if (i >= 20) {
        let up = 0;
        let down = 0;
        let ok = true;
        for (let k = i - 19; k <= i; k++) {
          const vol = bars[k].v;
          if (!finite(vol)) { ok = false; break; }
          const prev = bars[k - 1].c;
          if (!pos(prev)) { ok = false; break; }
          if (bars[k].c > prev) up += vol;
          else if (bars[k].c < prev) down += vol;
          else { up += vol / 2; down += vol / 2; }
        }
        const tot = up + down;
        if (ok && tot > 0) {
          const buy = up / tot;
          pressure[i] = {
            buy: buy,
            color: buy >= 0.55 ? "green" : buy <= 0.45 ? "red" : "yellow",
          };
        }
      }
      const s50 = sma[50][i];
      if (pos(s50)) {
        const ext = bars[i].c / s50 - 1;
        let color = "red";
        let label = "more than 15% above the 50-day";
        if (ext < 0) { color = "red"; label = "below the 50-day"; }
        else if (ext <= 0.08) { color = "green"; label = "within 8% above the 50-day"; }
        else if (ext <= 0.15) { color = "yellow"; label = "8% to 15% above the 50-day"; }
        risk[i] = { ext: ext, color: color, label: label };
      }
      if (i >= 252) {
        let score = 0;
        let ok = true;
        for (let w = 0; w < RS_WEIGHTS.length; w++) {
          const back = RS_WEIGHTS[w][0];
          const weight = RS_WEIGHTS[w][1];
          const prev = bars[i - back].c;
          if (!pos(prev) || !pos(bars[i].c)) { ok = false; break; }
          score += weight * (bars[i].c / prev - 1);
        }
        if (ok) wscore[i] = score;
      }
    }
    return {
      bars: bars, sma: sma, relVol: relVol, dry: dry, pressure: pressure,
      risk: risk, wscore: wscore, rank: rank, grade: grade,
    };
  }

  function percentileRanks(values) {
    const n = values.length;
    const out = new Array(n).fill(null);
    if (n < 2) return out;
    const order = values.map((v, i) => i).sort((a, b) => values[a] - values[b] || a - b);
    let i = 0;
    while (i < n) {
      let j = i;
      while (j + 1 < n && values[order[j + 1]] === values[order[i]]) j += 1;
      const avgIndex = (i + j) / 2;
      const pct = avgIndex / (n - 1);
      const rank = clamp(Math.round(1 + pct * 98), 1, 99);
      for (let k = i; k <= j; k++) out[order[k]] = rank;
      i = j + 1;
    }
    return out;
  }

  function calendar(stocks, sessions) {
    let ref = null;
    stocks.forEach((s) => {
      if (!s.bars.length) return;
      const last = s.bars[s.bars.length - 1].d;
      if (!ref || last > ref.bars[ref.bars.length - 1].d || (last === ref.bars[ref.bars.length - 1].d && s.bars.length > ref.bars.length)) ref = s;
    });
    if (!ref) return [];
    return ref.bars.slice(-sessions).map((b) => b.d);
  }

  function rankDates(stocks, dates) {
    const indexOf = stocks.map((s) => {
      const m = new Map();
      s.bars.forEach((b, i) => m.set(b.d, i));
      return m;
    });
    dates.forEach((d) => {
      const scored = [];
      stocks.forEach((s, si) => {
        const i = indexOf[si].get(d);
        if (i == null) return;
        const w = s.wscore[i];
        if (!finite(w)) return;
        scored.push({ s: s, i: i, w: w });
      });
      const ranks = percentileRanks(scored.map((x) => x.w));
      scored.forEach((x, k) => { x.s.rank[x.i] = ranks[k]; });
    });
  }

  function highLow(bars, i, n) {
    if (i < n - 1) return null;
    let hi = -Infinity;
    let lo = Infinity;
    for (let k = i - (n - 1); k <= i; k++) {
      if (!pos(bars[k].h) || !pos(bars[k].l)) return null;
      if (bars[k].h > hi) hi = bars[k].h;
      if (bars[k].l < lo) lo = bars[k].l;
    }
    if (!pos(hi) || !pos(lo)) return null;
    return { hi: hi, lo: lo };
  }

  function gradeAt(s, i) {
    const bar = s.bars[i];
    if (!bar) return null;
    const checks = [];
    const sma = s.sma;
    const c = bar.c;
    const s50 = sma[50][i];
    const s150 = sma[150][i];
    const s200 = sma[200][i];
    const s200prev = i >= 21 ? sma[200][i - 21] : null;
    checks.push({
      id: "above50",
      label: "Close above the 50-day average",
      state: pos(s50) ? (c > s50 ? "pass" : "fail") : "missing",
    });
    checks.push({
      id: "stack",
      label: "50-day above the 150-day and the 150-day above the 200-day",
      state: pos(s50) && pos(s150) && pos(s200) ? (s50 > s150 && s150 > s200 ? "pass" : "fail") : "missing",
    });
    checks.push({
      id: "rise200",
      label: "200-day average higher than 21 sessions ago",
      state: pos(s200) && pos(s200prev) ? (s200 > s200prev ? "pass" : "fail") : "missing",
    });
    const hl = highLow(s.bars, i, 252);
    checks.push({
      id: "low30",
      label: "Close at least 30% above the 252-session low",
      state: hl ? (c >= hl.lo * 1.3 ? "pass" : "fail") : "missing",
    });
    checks.push({
      id: "high25",
      label: "Close within 25% of the 252-session high",
      state: hl ? (c >= hl.hi * 0.75 ? "pass" : "fail") : "missing",
    });
    const rank = s.rank[i];
    checks.push({
      id: "rank80",
      label: "12-month rank at least 80",
      state: finite(rank) ? (rank >= 80 ? "pass" : "fail") : "missing",
    });
    const known = checks.filter((x) => x.state !== "missing");
    if (known.length < 5) return { letter: null, checks: checks, pass: known.filter((x) => x.state === "pass").length, known: known.length };
    const pass = known.filter((x) => x.state === "pass").length;
    const fail = known.length - pass;
    let letter = "D";
    if (pass >= 5 && fail === 0) letter = "A";
    else if (pass >= 4 && fail <= 1) letter = "B";
    else if (pass >= 3 && fail <= 2) letter = "C";
    return { letter: letter, checks: checks, pass: pass, known: known.length };
  }

  function stageAt(s, i) {
    const c = s.bars[i] && s.bars[i].c;
    const s200 = s.sma[200][i];
    const prev = i >= 21 ? s.sma[200][i - 21] : null;
    if (!pos(c) || !pos(s200) || !pos(prev)) return { stage: null, reason: "Needs a 200-day average and the value 21 sessions earlier." };
    const slope = s200 / prev - 1;
    const rising = slope >= 0.005;
    const falling = slope <= -0.005;
    const above = c > s200;
    let stage = 1;
    if (above && rising) stage = 2;
    else if (above && falling) stage = 3;
    else if (!above && falling) stage = 4;
    else stage = 1;
    return { stage: stage, slope: slope, above: above };
  }

  function templateAt(s, i) {
    const bar = s.bars[i];
    const c = bar.c;
    const sma = s.sma;
    const hl = highLow(s.bars, i, 252);
    const s200 = sma[200][i];
    const s200p = i >= 21 ? sma[200][i - 21] : null;
    const items = [
      { id: "t1", label: "Close above the 150-day and the 200-day", state: pos(sma[150][i]) && pos(s200) ? (c > sma[150][i] && c > s200 ? "pass" : "fail") : "missing" },
      { id: "t2", label: "150-day above the 200-day", state: pos(sma[150][i]) && pos(s200) ? (sma[150][i] > s200 ? "pass" : "fail") : "missing" },
      { id: "t3", label: "200-day higher than 21 sessions ago", state: pos(s200) && pos(s200p) ? (s200 > s200p ? "pass" : "fail") : "missing" },
      { id: "t4", label: "50-day above the 150-day and the 200-day", state: pos(sma[50][i]) && pos(sma[150][i]) && pos(s200) ? (sma[50][i] > sma[150][i] && sma[50][i] > s200 ? "pass" : "fail") : "missing" },
      { id: "t5", label: "Close above the 50-day", state: pos(sma[50][i]) ? (c > sma[50][i] ? "pass" : "fail") : "missing" },
      { id: "t6", label: "Close at least 30% above the 252-session low", state: hl ? (c >= hl.lo * 1.3 ? "pass" : "fail") : "missing" },
      { id: "t7", label: "Close within 25% of the 252-session high", state: hl ? (c >= hl.hi * 0.75 ? "pass" : "fail") : "missing" },
      { id: "t8", label: "Our 12-month rank at least 70 (not a published third-party RS rating)", state: finite(s.rank[i]) ? (s.rank[i] >= 70 ? "pass" : "fail") : "missing" },
    ];
    return {
      items: items,
      pass: items.filter((x) => x.state === "pass").length,
      fail: items.filter((x) => x.state === "fail").length,
      missing: items.filter((x) => x.state === "missing").length,
      complete: items.every((x) => x.state === "pass"),
    };
  }

  function eventsAt(s, i) {
    const out = [];
    if (i < 1) return out;
    const b = s.bars[i];
    const p = s.bars[i - 1];
    const up = b.c > p.c;
    const dn = b.c < p.c;
    if (b.h > p.h) out.push({ side: "pos", net: true, text: "Higher high" });
    if (b.h < p.h && b.l > p.l) out.push({ side: "neg", net: true, text: "Inside day" });
    if (i >= 3) {
      let ups = 0;
      for (let k = 0; k < 3; k++) if (s.bars[i - k].c > s.bars[i - k - 1].c) ups += 1;
      if (ups >= 2) out.push({ side: "pos", net: true, text: ups + " of 3 days up" });
    }
    const rv = s.relVol[i];
    if (finite(rv) && rv >= 1.5 && up) out.push({ side: "pos", net: true, text: "Up on " + Math.round((rv - 1) * 100) + "% volume increase" });
    if (finite(rv) && rv >= 1.5 && dn) out.push({ side: "neg", net: true, text: "Down on " + Math.round((rv - 1) * 100) + "% volume increase" });
    const range = b.h - b.l;
    if (range > 0 && (b.c - b.l) / range >= 0.75 && up) out.push({ side: "pos", net: true, text: "Close on high" });
    if (pos(s.sma[10][i]) && b.c < s.sma[10][i]) out.push({ side: "neg", net: true, text: "Close below 10-day MA" });
    if (pos(s.sma[20][i]) && b.c < s.sma[20][i]) out.push({ side: "neg", net: true, text: "Close below 20-day MA" });
    if (dn && i >= 252) {
      const drop = b.c / p.c - 1;
      let worst = 0;
      let ok = true;
      for (let k = i - 251; k <= i; k++) {
        const prev = s.bars[k - 1];
        if (!prev || !pos(prev.c)) { ok = false; break; }
        const ch = s.bars[k].c / prev.c - 1;
        if (ch < worst) worst = ch;
      }
      if (ok && drop < 0 && drop === worst) {
        out.push({ side: "neg", net: true, text: "Largest down day (" + (drop * 100).toFixed(2) + "%)" });
        if (finite(rv) && rv >= 1.5) out.push({ side: "neg", net: true, text: "Largest down day on high volume" });
      }
    }
    if (finite(s.rank[i]) && s.rank[i] >= 70) out.push({ side: "pos", net: false, text: "Rank 70+" });
    if (i >= 252 && pos(s.bars[i - 252].c)) {
      const y = b.c / s.bars[i - 252].c - 1;
      if (y >= 0.25) out.push({ side: "neg", net: false, text: "Extended vs 252 sessions ago" });
    }
    const g = s.grade[i];
    if (g && g.letter) {
      const side = g.letter === "A" || g.letter === "B" ? "pos" : g.letter === "D" ? "neg" : "neutral";
      out.push({ side: side, net: false, text: "Grade " + g.letter });
    }
    return out;
  }

  function netOf(events) {
    let n = 0;
    events.forEach((e) => {
      if (!e.net) return;
      if (e.side === "pos") n += 1;
      else if (e.side === "neg") n -= 1;
    });
    return n;
  }

  function isSwing(bars, i, left, right, field, dir) {
    if (i < left || i + right >= bars.length) return false;
    const v = bars[i][field];
    for (let k = 1; k <= left; k++) {
      if (dir > 0 ? !(v > bars[i - k][field]) : !(v < bars[i - k][field])) return false;
    }
    for (let k = 1; k <= right; k++) {
      if (dir > 0 ? !(v > bars[i + k][field]) : !(v < bars[i + k][field])) return false;
    }
    return true;
  }

  function contractions(bars, asOf) {
    const start = Math.max(4, asOf - 120);
    const highs = [];
    const lows = [];
    for (let i = start; i + 3 <= asOf; i++) {
      if (isSwing(bars, i, 4, 3, "h", 1)) highs.push(i);
      if (isSwing(bars, i, 4, 3, "l", -1)) lows.push(i);
    }
    const found = [];
    for (let h = 0; h < highs.length; h++) {
      const hi = highs[h];
      const nextHigh = h + 1 < highs.length ? highs[h + 1] : asOf + 1;
      let low = null;
      for (let j = 0; j < lows.length; j++) {
        if (lows[j] > hi && lows[j] < nextHigh) low = lows[j];
      }
      if (low == null) continue;
      if (low - hi < 2) continue;
      const depth = (bars[hi].h - bars[low].l) / bars[hi].h;
      if (!(depth >= 0.03) || !pos(bars[hi].h)) continue;
      found.push({ hi: hi, low: low, depth: depth });
    }
    let run = [];
    let best = [];
    found.forEach((c) => {
      if (!run.length || c.depth < run[run.length - 1].depth) run.push(c);
      else run = [c];
      if (run.length >= best.length) best = run.slice();
    });
    return { all: found, tight: best };
  }

  function volMean(bars, a, b) {
    if (b < a) return null;
    let sum = 0;
    let n = 0;
    for (let i = a; i <= b; i++) {
      if (!finite(bars[i].v)) return null;
      sum += bars[i].v;
      n += 1;
    }
    return n ? sum / n : null;
  }

  function priorHigh(bars, i, n) {
    if (i < n) return null;
    let hi = -Infinity;
    for (let k = i - n; k < i; k++) {
      if (!pos(bars[k].h)) return null;
      if (bars[k].h > hi) hi = bars[k].h;
    }
    return pos(hi) ? hi : null;
  }

  function letterAt(s, back) {
    const i = s.bars.length - 1 - back;
    if (i < 0) return null;
    const g = s.grade[i];
    return g && g.letter ? g.letter : null;
  }

  function finalizeStock(s, meta) {
    const n = s.bars.length;
    const i = n - 1;
    s.last = i;
    s.date = n ? s.bars[i].d : "";
    s.close = n ? s.bars[i].c : null;
    s.chg = n >= 2 && pos(s.bars[i - 1].c) ? s.bars[i].c / s.bars[i - 1].c - 1 : null;
    const from = Math.max(0, n - 252);
    for (let k = from; k < n; k++) s.grade[k] = gradeAt(s, k);
    s.template = n ? templateAt(s, i) : { items: [], pass: 0, fail: 0, missing: 8, complete: false };
    s.stage = n ? stageAt(s, i) : { stage: null, reason: "No bars" };
    const hl = n ? highLow(s.bars, i, 252) : null;
    s.offHigh = hl && pos(hl.hi) ? s.close / hl.hi - 1 : null;
    s.hl = hl;
    const events = [];
    for (let k = Math.max(1, n - 40); k < n; k++) {
      const ev = eventsAt(s, k);
      events.push({ date: s.bars[k].d, index: k, events: ev, net: netOf(ev) });
    }
    s.recent = events;
    const pack = contractions(s.bars, Math.max(0, i));
    let vcp = { candidate: false, reason: "Not enough confirmed swings.", count: pack.tight.length };
    if (s.template.missing) vcp = { candidate: false, reason: "Trend template is missing an input.", count: pack.tight.length, skipped: true };
    else if (!s.template.complete) vcp = { candidate: false, reason: "Trend template is not 8 of 8.", count: pack.tight.length };
    else if (pack.tight.length < 2) vcp = { candidate: false, reason: "Fewer than two tightening contractions in the last 120 sessions.", count: pack.tight.length };
    else {
      const a = pack.tight[pack.tight.length - 2];
      const b = pack.tight[pack.tight.length - 1];
      const va = volMean(s.bars, a.hi, a.low);
      const vb = volMean(s.bars, b.hi, b.low);
      if (va == null || vb == null) vcp = { candidate: false, reason: "Contraction volume is missing.", count: pack.tight.length, skipped: true };
      else if (!(vb < va)) vcp = { candidate: false, reason: "The later contraction did not print lower average volume.", count: pack.tight.length };
      else vcp = { candidate: true, reason: "Two or more tighter contractions and lower volume on the latest one. A candidate, not a certified pattern.", count: pack.tight.length, pivot: s.bars[b.hi].h };
    }
    s.vcp = vcp;
    const pivot20 = n ? priorHigh(s.bars, i, 20) : null;
    s.pivot20 = pivot20;
    s.patterns = {
      tight: tightState(s, i),
      near: nearState(s, i, pivot20),
      breakout: breakoutState(s, i, pivot20),
    };
    s.stale = !!(meta && meta.price_as_of && s.date && s.date < meta.price_as_of);
    s.company = s.company || "";
    s.sector = s.sector || "";
  }

  function tightState(s, i) {
    if (i < 14) return { state: "skip", reason: "Needs 15 sessions." };
    let hi = -Infinity;
    let lo = Infinity;
    for (let k = i - 14; k <= i; k++) {
      hi = Math.max(hi, s.bars[k].h);
      lo = Math.min(lo, s.bars[k].l);
    }
    const mid = (hi + lo) / 2;
    if (!pos(mid)) return { state: "skip", reason: "Range is not usable." };
    const width = (hi - lo) / mid;
    const dry = s.dry[i];
    const s50 = s.sma[50][i];
    if (!finite(dry) || !pos(s50)) return { state: "skip", reason: "Dry-up ratio or the 50-day average is missing." };
    const ok = width <= 0.08 && dry <= 0.70 && s.bars[i].c > s50;
    return { state: ok ? "match" : "no", width: width, dry: dry };
  }

  function nearState(s, i, pivot) {
    if (!pos(pivot) || !pos(s.sma[50][i])) return { state: "skip", reason: "Needs a 20-session high and a 50-day average." };
    const c = s.bars[i].c;
    const dist = (pivot - c) / pivot;
    const ok = c < pivot && dist <= 0.03 && dist >= 0 && c > s.sma[50][i];
    return { state: ok ? "match" : "no", dist: dist, pivot: pivot };
  }

  function breakoutState(s, i, pivot) {
    if (!pos(pivot) || !finite(s.relVol[i])) return { state: "skip", reason: "Needs a 20-session high and relative volume." };
    const ok = s.bars[i].c > pivot && s.relVol[i] >= 1.5;
    return { state: ok ? "match" : "no", pivot: pivot, rel: s.relVol[i] };
  }

  function buildDesk(records, meta) {
    const stocks = (records || []).map((r) => {
      const parsed = parseBars(r.bars || r.rows || []);
      const s = analyzeBars(parsed.bars);
      s.ticker = String(r.ticker || "").toUpperCase();
      s.company = r.company || "";
      s.sector = r.sector || "";
      s.score = r.score || null;
      s.dropped = parsed.dropped;
      return s;
    }).filter((s) => s.ticker);
    const dates = calendar(stocks, 252);
    rankDates(stocks, dates);
    stocks.forEach((s) => finalizeStock(s, meta || {}));
    const screens = SCREEN_DEFS.map((def) => evaluateScreen(def, stocks));
    return { stocks: stocks, dates: dates, screens: screens, coverage: COVERAGE };
  }

  function rankNow(s) {
    return s.last >= 0 ? s.rank[s.last] : null;
  }
  function gradeNow(s) {
    if (s.last < 0) return null;
    const g = s.grade[s.last];
    return g && g.letter ? g.letter : null;
  }
  function gradeBack(s, back) {
    const i = s.last - back;
    if (i < 0) return null;
    const g = s.grade[i];
    return g && g.letter ? g.letter : null;
  }

  function tri(s, pred) {
    try {
      return pred(s);
    } catch (err) {
      return "skip";
    }
  }

  const SCREEN_DEFS = [
    { id: "bread", ref: "Bread & Butter", ourName: "Bread & Butter", status: "enabled",
      evidence: "UI label only. The published formula was not found. This is our checklist.",
      formula: "Trend template 8 of 8, stage 2, leadership grade A or B, and the close within 15% of the 252-session high.",
      data: "252 sessions, 200-day average, 12-month rank.",
      match: (s) => tri(s, () => !s.template || s.template.missing ? "skip" : (s.template.complete && s.stage.stage === 2 && (gradeNow(s) === "A" || gradeNow(s) === "B") && finite(s.offHigh) && s.offHigh >= -0.15) ? "match" : "no") },
    { id: "gradeA", ref: "Grade A", ourName: "Grade A", status: "enabled",
      evidence: "Sample grade letters. The third-party grade formula is not published.",
      formula: "Our leadership grade is A (at least 5 of 6 checks known, all of those pass, and at least 5 pass).",
      data: "Same six checks as the grade.",
      match: (s) => gradeNow(s) ? (gradeNow(s) === "A" ? "match" : "no") : "skip" },
    { id: "gradeAB", ref: "Grade A & B", ourName: "Grade A and B", status: "enabled",
      evidence: "Sample screen. Our grade, not a published letter formula.",
      formula: "Leadership grade A or B.",
      data: "Grade inputs.",
      match: (s) => { const g = gradeNow(s); return g ? ((g === "A" || g === "B") ? "match" : "no") : "skip"; } },
    { id: "gradeUp", ref: "Grade Moving Up", ourName: "Grade moving up", status: "enabled",
      evidence: "Sample screen. Comparison uses our letters.",
      formula: "Today's grade is better than the grade 21 sessions ago. A is best, then B, C, D.",
      data: "Grade on both dates.",
      match: (s) => { const a = gradeNow(s); const b = gradeBack(s, 21); if (!a || !b) return "skip"; return GRADE_ORDER[a] > GRADE_ORDER[b] ? "match" : "no"; } },
    { id: "tight", ref: "Tight Price Low Volume", ourName: "Tight price, low volume", status: "enabled",
      evidence: "Sample screen. Thresholds below are ours.",
      formula: "Last 15 sessions' high-to-low range is at most 8% of the midpoint, the 10-session volume is at most 70% of the prior 50, and the close is above the 50-day.",
      data: "15 price sessions, 60 volume sessions, 50-day average.",
      match: (s) => s.patterns.tight.state === "match" ? "match" : s.patterns.tight.state },
    { id: "rank89", ref: "RPR 89+ Grade C+", ourName: "Rank 89+ and grade C+", status: "enabled",
      evidence: "RPR is not published. The number here is our 1–99 rank.",
      formula: "12-month rank at least 89 and grade A, B, or C.",
      data: "Rank and grade.",
      match: (s) => { const r = rankNow(s); const g = gradeNow(s); if (!finite(r) || !g) return "skip"; return r >= 89 && g !== "D" ? "match" : "no"; } },
    { id: "lead5", ref: "Fab 5 (RPR 70+)", ourName: "Leadership Five", status: "enabled",
      evidence: "The five published components were not found. This is not that ranking.",
      formula: "Stage 2, pressure green, entry risk green, rank at least 70, and grade A or B. All five must be known.",
      data: "Stage, 20-session pressure, 50-day extension, rank, grade.",
      match: (s) => {
        const p = s.last >= 0 ? s.pressure[s.last] : null;
        const risk = s.last >= 0 ? s.risk[s.last] : null;
        const g = gradeNow(s);
        if (!s.stage.stage || !p || !risk || !finite(rankNow(s)) || !g) return "skip";
        return s.stage.stage === 2 && p.color === "green" && risk.color === "green" && rankNow(s) >= 70 && (g === "A" || g === "B") ? "match" : "no";
      } },
    { id: "riskGreen", ref: "Buy Risk Green", ourName: "Entry risk green", status: "enabled",
      evidence: "Buy Risk is not published. Green here means our entry-risk band.",
      formula: "Close is above the 50-day and at most 8% above it.",
      data: "50-day average.",
      match: (s) => { const risk = s.last >= 0 ? s.risk[s.last] : null; return risk ? (risk.color === "green" ? "match" : "no") : "skip"; } },
    { id: "ipo", ref: "IPOs (Stocks)", ourName: "IPOs", status: "unavailable",
      evidence: "No listing date is stored. The first bar in a file is the cache start, not an IPO.",
      formula: "Not computed. A short file is not treated as an IPO.",
      data: "Listing date, which this desk does not publish.",
      match: () => "skip" },
    { id: "powerIpo", ref: "Power IPO", ourName: "Power IPO", status: "unavailable",
      evidence: "Power Play thresholds were not verified, and listing dates are not stored.",
      formula: "Not computed. Not claimed as a copy.",
      data: "Listing date and a verified power-play rule.",
      match: () => "skip" },
    { id: "top5", ref: "Top 5% RPR", ourName: "Top 5% rank", status: "enabled",
      evidence: "Our rank, scaled 1 to 99. Ranks 95 through 99 are the top slice.",
      formula: "12-month rank at least 95.",
      data: "Rank.",
      match: (s) => finite(rankNow(s)) ? (rankNow(s) >= 95 ? "match" : "no") : "skip" },
    { id: "newTop5", ref: "New Top 5% RPR", ourName: "New top 5% rank", status: "enabled",
      evidence: "Our rank on two dates. No future sessions.",
      formula: "Rank at least 95 today and rank under 95 on the session 21 bars ago.",
      data: "Rank on both dates.",
      match: (s) => {
        const now = rankNow(s);
        const prev = s.last >= 21 ? s.rank[s.last - 21] : null;
        if (!finite(now) || !finite(prev)) return "skip";
        return now >= 95 && prev < 95 ? "match" : "no";
      } },
    { id: "momentum", ref: "Momentum ($10+)", ourName: "Momentum, $10+", status: "enabled",
      evidence: "Sample name. The momentum model is ours.",
      formula: "Close at least $10, rank at least 80, close above the 50-day, and the 63-session return positive.",
      data: "Close, rank, 50-day, 63 sessions.",
      match: (s) => {
        if (s.last < 63 || !pos(s.sma[50][s.last]) || !finite(rankNow(s)) || !pos(s.bars[s.last - 63].c)) return "skip";
        const ret = s.close / s.bars[s.last - 63].c - 1;
        return s.close >= 10 && rankNow(s) >= 80 && s.close > s.sma[50][s.last] && ret > 0 ? "match" : "no";
      } },
    { id: "trendQual", ref: "Trend Qualifier", ourName: "Trend qualifier", status: "enabled",
      evidence: "Public trend idea, measured our way. Not a third-party qualifier score.",
      formula: "Close above the 50-day and the 200-day, the 50-day above the 200-day, and the 200-day higher than 21 sessions ago.",
      data: "50-day, 200-day, 21-session slope.",
      match: (s) => {
        const i = s.last;
        if (i < 0 || !pos(s.sma[50][i]) || !pos(s.sma[200][i]) || i < 21 || !pos(s.sma[200][i - 21])) return "skip";
        return s.close > s.sma[50][i] && s.close > s.sma[200][i] && s.sma[50][i] > s.sma[200][i] && s.sma[200][i] > s.sma[200][i - 21] ? "match" : "no";
      } },
    { id: "gradeJump", ref: "Grade Jump 2+", ourName: "Grade jump of 2", status: "enabled",
      evidence: "Our letters, 21 sessions apart.",
      formula: "Grade improved by two letters or more versus 21 sessions ago (D to B, D to A, or C to A).",
      data: "Grade on both dates.",
      match: (s) => { const a = gradeNow(s); const b = gradeBack(s, 21); if (!a || !b) return "skip"; return GRADE_ORDER[a] - GRADE_ORDER[b] >= 2 ? "match" : "no"; } },
    { id: "gradeDtoB", ref: "Grade D to B+", ourName: "Grade D to B+", status: "enabled",
      evidence: "Our letters.",
      formula: "Grade was D 21 sessions ago and is A or B today.",
      data: "Grade on both dates.",
      match: (s) => { const a = gradeNow(s); const b = gradeBack(s, 21); if (!a || !b) return "skip"; return b === "D" && (a === "A" || a === "B") ? "match" : "no"; } },
    { id: "gradeD200", ref: "Grade D – Below 200d", ourName: "Grade D below the 200-day", status: "enabled",
      evidence: "Our grade plus the 200-day average.",
      formula: "Grade D and the close under the 200-day average.",
      data: "Grade and 200-day average.",
      match: (s) => {
        const g = gradeNow(s);
        if (!g || s.last < 0 || !pos(s.sma[200][s.last])) return "skip";
        return g === "D" && s.close < s.sma[200][s.last] ? "match" : "no";
      } },
    { id: "stage2", ref: "Stage 2 ($10+)", ourName: "Stage 2, $10+", status: "enabled",
      evidence: "Stage labels follow the public stage idea with our 0.5% slope band. Not a product stage rating.",
      formula: "Stage 2 and the close at least $10.",
      data: "200-day average and its value 21 sessions ago.",
      match: (s) => s.stage.stage == null || !pos(s.close) ? "skip" : (s.stage.stage === 2 && s.close >= 10 ? "match" : "no") },
    { id: "template", ref: "Trend Template", ourName: "Trend template", status: "enabled",
      evidence: "The eight-point checklist is the published trend template. Measurement choices (simple averages, 21 sessions, 252-session high and low, our rank for the RS line) are stated. Our rank is not a third-party RS rating.",
      formula: "All eight template checks pass. A missing check keeps the stock out rather than failing it.",
      data: "150, 200, and 50-day averages, 252-session high and low, rank.",
      match: (s) => !s.template || s.template.missing ? "skip" : (s.template.complete ? "match" : "no") },
    { id: "vcp", ref: "VCP / tight base", ourName: "Tight-base candidate", status: "enabled",
      evidence: "Contraction examples in published books are examples, not a hard rule. This candidate uses the desk's published swing settings (4 left, 3 right, tie is not a swing) plus two tighter contractions and lower volume. It is not a certified visual pattern.",
      formula: "Template 8 of 8, at least two successive tighter contractions of at least 3% in the last 120 confirmed sessions, and lower average volume on the later contraction.",
      data: "Template inputs plus swing highs and lows and volume.",
      match: (s) => s.vcp.skipped ? "skip" : (s.vcp.candidate ? "match" : "no") },
    { id: "dry", ref: "Volume dry-up", ourName: "Volume dry-up", status: "enabled",
      evidence: "Our volume window. Not an institutional-intent reading.",
      formula: "10-session average volume is at most 60% of the 50 sessions before that window, the close is above the 50-day, and the close is within 15% of the 63-session high.",
      data: "60 volume sessions, 50-day average, 63-session high.",
      match: (s) => {
        const i = s.last;
        if (i < 62 || !finite(s.dry[i]) || !pos(s.sma[50][i])) return "skip";
        const hi = priorHigh(s.bars, i + 1, 63);
        if (!pos(hi)) return "skip";
        return s.dry[i] <= 0.60 && s.close > s.sma[50][i] && s.close >= hi * 0.85 ? "match" : "no";
      } },
    { id: "breakout", ref: "Breakout volume", ourName: "Breakout volume", status: "enabled",
      evidence: "Our pivot is the prior 20-session high. Not a certified base breakout.",
      formula: "Close above the highest high of the prior 20 sessions, and volume at least 1.5 times the prior 50-session average. Today's volume is not inside that average.",
      data: "21 sessions of highs and 51 volume sessions.",
      match: (s) => s.patterns.breakout.state === "match" ? "match" : s.patterns.breakout.state },
    { id: "near", ref: "Near buy point", ourName: "Near buy point", status: "enabled",
      evidence: "Our buy point is the prior 20-session high. The stock-box entry zone, when the score file has one, is drawn separately.",
      formula: "Close is under that high by at most 3% and still above the 50-day.",
      data: "20 prior highs and the 50-day average.",
      match: (s) => s.patterns.near.state === "match" ? "match" : s.patterns.near.state },
  ];

  const COVERAGE = SCREEN_DEFS.map((d) => ({
    ref: d.ref,
    ourName: d.ourName,
    id: d.id,
    status: d.status,
    evidence: d.evidence,
    formula: d.formula,
    data: d.data,
    tested: d.status === "enabled",
  })).concat([
    { ref: "RPR", ourName: "12-month rank", id: "rank", status: "enabled", evidence: "Weighting matches the published 40/20/20/20 quarter method. The universe is this desk, so the number is not a third-party RS or RPR.", formula: "0.40 times the 63-session return, plus 0.20 times each of the three prior 63-session returns. Percentile rank from 1 to 99 with tie midpoints. A missing leg leaves the score out of the ranking.", data: "252 stored sessions and at least two names.", tested: true },
    { ref: "TPR / grade", ourName: "Leadership grade", id: "grade", status: "enabled", evidence: "Letter formulas are not published.", formula: "Six pass/fail checks. Fewer than five known checks leaves the grade blank. A is 5 or more passes and no fails. B is at least 4 passes and at most 1 fail. C is at least 3 passes and at most 2 fails. Otherwise D.", data: "Averages, 252-session high and low, rank.", tested: true },
    { ref: "Pressure", ourName: "Price-volume pressure", id: "pressure", status: "enabled", evidence: "Not a published pressure formula and not a read of institutional intent.", formula: "Over 20 sessions, up-close volume versus down-close volume. A flat close splits that session's volume in half. Green at or above 55% up volume, red at or below 45%, yellow between. A missing volume session leaves the window blank.", data: "20 sessions with volume and a prior close.", tested: true },
    { ref: "Buy Risk", ourName: "Entry risk", id: "risk", status: "enabled", evidence: "Not a published buy-risk formula.", formula: "Percent the close sits above the 50-day simple average. Green: above it and at most 8%. Yellow: more than 8% and at most 15%. Red: more than 15%, or below the average.", data: "50-day average.", tested: true },
    { ref: "Alert net", ourName: "Alert net", id: "net", status: "enabled", evidence: "Daily confirmations and warnings are named in public material. The net count is ours.", formula: "Plus one for a higher high, 2 or 3 up closes in 3 sessions, an up close on at least 1.5 times prior-50 volume, and a close in the top quarter of the range. Minus one for an inside day, a down close on that volume, a close under the 10-day, a close under the 20-day, and a largest 252-session down close. Rank and grade chips are shown and are not in the net.", data: "Daily bars. The largest-down-day term needs 252 sessions.", tested: true },
    { ref: "Relative volume", ourName: "Relative volume", id: "relvol", status: "enabled", evidence: "Our volume reading. Separate from dry-up and from pressure.", formula: "Today's volume divided by the average of the 50 sessions before today. Today is not in the baseline. A later session is not used. A missing or non-numeric volume in the baseline leaves the ratio blank. A zero baseline is blank.", data: "51 volume sessions.", tested: true },
    { ref: "Volume contraction", ourName: "Dry-up ratio", id: "dryratio", status: "enabled", evidence: "Our windows, chosen so the recent 10 sessions are not inside their own baseline.", formula: "Average volume of the last 10 sessions, including today, divided by the average of the 50 sessions before those 10.", data: "60 volume sessions.", tested: true },
    { ref: "SPY 25 / QQQ 33 / STEM", ourName: "Desk regime", id: "regime", status: "enabled", evidence: "Those timing models are not published and are not computed. SPY and QQQ daily bars are not in the published per-ticker files.", formula: "UPTREND when the stored share of names above the 50-day is at least 60%, the share above the 200-day is at least 55%, and advancers are at least decliners when both counts exist. DEFENSIVE when either breadth share is under 40%. Otherwise MIXED. Missing breadth leaves the regime unavailable.", data: "market_today.csv breadth and advancer counts. Not index OHLC.", tested: true },
    { ref: "Power Play / 3C", ourName: "Not copied", id: "powerplay", status: "unavailable", evidence: "Thresholds were not verified. No screen claims those names.", formula: "Not implemented.", data: "A verified rule, which we do not have.", tested: false },
    { ref: "Quarterly sales", ourName: "Sales", id: "sales", status: "unavailable", evidence: "earnings_history.csv has EPS, not quarterly sales. Annual revenue on company_financials is not a quarterly sales series.", formula: "Shown as unavailable. EPS is shown only where an actual is stored.", data: "Quarterly sales feed.", tested: false },
    { ref: "SBE", ourName: "Partial sale to cover stop risk", id: "sbe", status: "enabled", evidence: "The idea is public. The exact product formula was not published. This is our algebra.", formula: "Fraction sold f = (entry - stop) / (sale - stop - fee). Sale must be above entry, stop below entry. Assumes the remaining shares are stopped exactly at the stop, with no gap.", data: "User entry, stop, sale, fee.", tested: true },
    { ref: "RBAF", ourName: "Scenario trade count", id: "rbaf", status: "enabled", evidence: "A quoted book example works out to about 60 trades on the linear form. Compounding the same inputs does not. Neither number is a forecast.", formula: "Edge = win rate times average gain minus loss rate times average loss, minus fee. Portfolio edge = position size times that edge. Linear trades = target divided by portfolio edge. Compound trades = ln(1+target) / ln(1+portfolio edge). Non-positive edge returns no trade count.", data: "User scenario inputs.", tested: true },
    { ref: "DRMA", ourName: "Return-bin table", id: "bins", status: "enabled", evidence: "A third-party DRMA formula was not verified. The column math is ours and is labeled on the page.", formula: "Closed-trade percent results in 2-point bins. Gain share and loss share are counts divided by closed trades. Contribution = bin midpoint in percent points times (gains minus losses) divided by closed trades.", data: "User paper fills.", tested: true },
  ]);

  function evaluateScreen(def, stocks) {
    if (def.status !== "enabled") {
      return { id: def.id, ref: def.ref, ourName: def.ourName, status: "unavailable", evidence: def.evidence, formula: def.formula, data: def.data, matches: null, evaluated: 0, skipped: stocks.length };
    }
    const matches = [];
    let skipped = 0;
    let evaluated = 0;
    stocks.forEach((s) => {
      if (!s.bars.length) { skipped += 1; return; }
      const r = def.match(s);
      if (r === "skip") skipped += 1;
      else {
        evaluated += 1;
        if (r === "match") matches.push(s.ticker);
      }
    });
    return { id: def.id, ref: def.ref, ourName: def.ourName, status: "enabled", evidence: def.evidence, formula: def.formula, data: def.data, matches: matches, evaluated: evaluated, skipped: skipped };
  }

  function regimeFromMarket(row) {
    const num = (v) => {
      const n = Number(v);
      return finite(n) ? n : null;
    };
    const b50 = num(row && row.breadth_sma50);
    const b200 = num(row && row.breadth_sma200);
    const adv = num(row && row.advancers);
    const dec = num(row && row.decliners);
    const base = {
      spyDay: num(row && row.spy_day_pct),
      qqqDay: num(row && row.qqq_day_pct),
      spyPrice: num(row && row.spy_price),
      asOf: row && row.price_as_of || "",
      b50: b50, b200: b200, adv: adv, dec: dec,
      note: "This regime uses stored breadth. It is not a SPY 25 model, a QQQ 33 model, or STEM. Daily SPY and QQQ bars are not in the published OHLC files, so those models are not computed.",
    };
    if (b50 == null || b200 == null) {
      return Object.assign(base, { status: "unavailable", label: "Unavailable", reason: "Breadth percentages are missing from market_today.csv." });
    }
    let label = "MIXED";
    if (b50 >= 60 && b200 >= 55 && (adv == null || dec == null || adv >= dec)) label = "UPTREND";
    else if (b50 < 40 || b200 < 40) label = "DEFENSIVE";
    return Object.assign(base, { status: "ok", label: label, reason: "Thresholds: uptrend is 50-day breadth at least 60, 200-day breadth at least 55, and advancers not below decliners. Defensive is either breadth share under 40." });
  }

  function summarize(s) {
    if (!s || !s.bars.length) return { text: "No stored daily bars for this symbol.", chips: [] };
    const i = s.last;
    const bits = [];
    const chips = [];
    bits.push(s.ticker + " as of " + s.date + ".");
    if (s.stale) bits.push("The last stored bar is older than the desk's price date.");
    if (s.stage.stage) bits.push("Stage " + s.stage.stage + " on our rule (200-day slope over 21 sessions, flat band 0.5%).");
    else bits.push(s.stage.reason || "Stage is unavailable.");
    bits.push("Trend template " + s.template.pass + " pass, " + s.template.fail + " fail, " + s.template.missing + " missing.");
    const g = gradeNow(s);
    bits.push(g ? "Leadership grade " + g + "." : "Leadership grade is unavailable.");
    const r = rankNow(s);
    bits.push(finite(r) ? "12-month rank " + r + " inside this desk (not a third-party RS rating)." : "12-month rank is unavailable.");
    const p = s.pressure[i];
    if (p) {
      bits.push("Pressure " + p.color + ", " + (p.buy * 100).toFixed(1) + "% of the 20-session price-volume on up closes. This is not an institutional-intent reading.");
      chips.push({ side: p.color === "red" ? "neg" : p.color === "green" ? "pos" : "neutral", text: "Pressure " + p.color });
    } else bits.push("Pressure is unavailable.");
    const risk = s.risk[i];
    if (risk) {
      bits.push("Entry risk is " + risk.color + ": " + risk.label + " (" + (risk.ext * 100).toFixed(1) + "% versus the 50-day).");
      chips.push({ side: risk.color === "red" ? "neg" : risk.color === "green" ? "pos" : "neutral", text: "Entry risk " + risk.color });
    } else bits.push("Entry risk is unavailable.");
    if (finite(s.relVol[i])) bits.push("Relative volume " + s.relVol[i].toFixed(2) + " times the prior 50 sessions. Today is outside that average.");
    else bits.push("Relative volume is unavailable.");
    if (finite(s.dry[i])) bits.push("Dry-up ratio " + s.dry[i].toFixed(2) + " (last 10 sessions over the 50 before them).");
    else bits.push("Dry-up ratio is unavailable.");
    const today = s.recent.length ? s.recent[s.recent.length - 1] : null;
    if (today) {
      bits.push("Alert net " + (today.net > 0 ? "+" : "") + today.net + " on " + today.date + ".");
      today.events.forEach((e) => chips.push(e));
    }
    bits.push("This paragraph only restates those calculations. It is not a language-model opinion and it is not a recommendation.");
    return { text: bits.join(" "), chips: chips };
  }

  function weekMonday(iso) {
    const dt = new Date(iso + "T00:00:00Z");
    const day = dt.getUTCDay();
    const delta = day === 0 ? 6 : day - 1;
    dt.setUTCDate(dt.getUTCDate() - delta);
    return dt.toISOString().slice(0, 10);
  }

  function toWeekly(bars) {
    const out = [];
    let cur = null;
    bars.forEach((b) => {
      const week = weekMonday(b.d);
      if (!cur || cur.week !== week) {
        if (cur) out.push(cur);
        cur = { d: b.d, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v, week: week };
      } else {
        cur.d = b.d;
        cur.h = Math.max(cur.h, b.h);
        cur.l = Math.min(cur.l, b.l);
        cur.c = b.c;
        if (cur.v == null || b.v == null) cur.v = null;
        else cur.v += b.v;
      }
    });
    if (cur) out.push(cur);
    return out.map((b) => ({ d: b.d, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v }));
  }

  function dayDiff(a, b) {
    const da = Date.parse(a + "T00:00:00Z");
    const db = Date.parse(b + "T00:00:00Z");
    if (!finite(da) || !finite(db)) return null;
    return Math.round((db - da) / 86400000);
  }

  function normalizeFills(fills) {
    return (fills || []).map((f, idx) => ({
      id: f.id || "f" + idx,
      ticker: String(f.ticker || "").toUpperCase(),
      date: String(f.date || "").slice(0, 10),
      side: String(f.side || "buy").toLowerCase() === "sell" ? "sell" : "buy",
      shares: Number(f.shares),
      price: Number(f.price),
      fee: finite(Number(f.fee)) ? Number(f.fee) : 0,
      stop: f.stop == null || f.stop === "" ? null : Number(f.stop),
      pivot: f.pivot == null || f.pivot === "" ? null : Number(f.pivot),
      size: f.size || "",
      note: f.note || "",
      reviewed: !!f.reviewed,
    })).filter((f) => f.ticker && f.date && pos(f.shares) && pos(f.price) && finite(f.fee) && f.fee >= 0);
  }

  function roundTrips(fills) {
    const lots = {};
    const closed = [];
    const errors = [];
    const ordered = normalizeFills(fills).slice().sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : (a.id < b.id ? -1 : 1));
    ordered.forEach((f) => {
      if (!lots[f.ticker]) lots[f.ticker] = [];
      if (f.side === "buy") {
        lots[f.ticker].push({
          date: f.date, shares: f.shares, price: f.price,
          feeLeft: f.fee, stop: f.stop, pivot: f.pivot, size: f.size, id: f.id, note: f.note,
        });
        return;
      }
      let left = f.shares;
      const openShares = lots[f.ticker].reduce((s, lot) => s + lot.shares, 0);
      if (left - openShares > 1e-9) {
        errors.push({ id: f.id, ticker: f.ticker, text: "Sell is larger than the open shares." });
        return;
      }
      while (left > 1e-9 && lots[f.ticker].length) {
        const lot = lots[f.ticker][0];
        const take = Math.min(lot.shares, left);
        const buyFee = lot.shares > 0 ? lot.feeLeft * (take / lot.shares) : 0;
        const sellFee = f.shares > 0 ? f.fee * (take / f.shares) : 0;
        const pnl = (f.price - lot.price) * take - buyFee - sellFee;
        const cost = lot.price * take + buyFee;
        closed.push({
          ticker: f.ticker,
          entryDate: lot.date,
          exitDate: f.date,
          shares: take,
          entry: lot.price,
          exit: f.price,
          pnl: pnl,
          pnlPct: cost > 0 ? pnl / cost : null,
          holdDays: dayDiff(lot.date, f.date),
          stop: lot.stop,
          pivot: lot.pivot,
          size: lot.size,
          entryId: lot.id,
          exitId: f.id,
          note: lot.note,
        });
        lot.shares -= take;
        lot.feeLeft -= buyFee;
        left -= take;
        if (lot.shares <= 1e-9) lots[f.ticker].shift();
      }
    });
    const open = [];
    Object.keys(lots).forEach((ticker) => {
      lots[ticker].forEach((lot) => {
        if (lot.shares > 1e-9) open.push(Object.assign({ ticker: ticker }, lot));
      });
    });
    return { closed: closed, open: open, errors: errors, ordered: ordered };
  }

  function binRows(closed) {
    const rows = [];
    for (let lo = -30; lo < 40; lo += 2) rows.push({ lo: lo, hi: lo + 2, gains: 0, losses: 0 });
    let overflowGain = 0;
    let overflowLoss = 0;
    closed.forEach((t) => {
      if (!finite(t.pnlPct)) return;
      const pct = t.pnlPct * 100;
      const row = rows.find((r) => pct >= r.lo && pct < r.hi);
      if (!row) {
        if (pct >= 0) overflowGain += 1;
        else overflowLoss += 1;
        return;
      }
      if (t.pnl > 0) row.gains += 1;
      else if (t.pnl < 0) row.losses += 1;
    });
    const n = closed.filter((t) => finite(t.pnlPct)).length;
    return {
      n: n,
      rows: rows.map((r) => {
        const mid = (r.lo + r.hi) / 2;
        const up = n ? r.gains / n : 0;
        const down = n ? r.losses / n : 0;
        return {
          label: r.lo + "–" + r.hi + "%",
          gains: r.gains,
          losses: r.losses,
          up: up,
          down: down,
          net: up - down,
          contribution: n ? mid * (r.gains - r.losses) / n : 0,
        };
      }),
      overflow: { gains: overflowGain, losses: overflowLoss },
    };
  }

  function applyCap(closed, capPct) {
    if (!finite(capPct)) return closed;
    return closed.map((t) => {
      if (!finite(t.pnlPct) || t.pnlPct >= capPct) return t;
      const cost = t.pnlPct !== 0 ? t.pnl / t.pnlPct : t.entry * t.shares;
      const pnlPct = capPct;
      return Object.assign({}, t, { pnlPct: pnlPct, pnl: cost * pnlPct, capped: true });
    });
  }

  function statsFromClosed(closed, extra) {
    const opt = extra || {};
    const usable = closed.filter((t) => finite(t.pnlPct));
    const wins = usable.filter((t) => t.pnl > 0);
    const losses = usable.filter((t) => t.pnl < 0);
    const flats = usable.filter((t) => t.pnl === 0);
    const avgGain = wins.length ? mean(wins.map((t) => t.pnlPct)) : null;
    const avgLoss = losses.length ? mean(losses.map((t) => t.pnlPct)) : null;
    const expectancy = usable.length ? mean(usable.map((t) => t.pnlPct)) : null;
    const holds = usable.map((t) => t.holdDays).filter((d) => finite(d));
    const year = opt.year;
    const ytd = year ? usable.filter((t) => String(t.exitDate).slice(0, 4) === String(year)) : [];
    const ytdPct = ytd.length ? ytd.reduce((s, t) => s + t.pnl, 0) : null;
    let equity = finite(opt.startingCash) ? opt.startingCash : null;
    let peak = equity;
    let maxDd = null;
    if (equity != null) {
      maxDd = 0;
      usable.slice().sort((a, b) => a.exitDate < b.exitDate ? -1 : 1).forEach((t) => {
        equity += t.pnl;
        if (equity > peak) peak = equity;
        const dd = peak > 0 ? (equity - peak) / peak : null;
        if (dd != null && (maxDd == null || dd < maxDd)) maxDd = dd;
      });
    }
    return {
      closedN: usable.length,
      wins: wins.length,
      losses: losses.length,
      flats: flats.length,
      batting: usable.length ? wins.length / usable.length : null,
      avgGain: avgGain,
      avgLoss: avgLoss,
      payoff: avgGain != null && avgLoss != null && avgLoss !== 0 ? avgGain / Math.abs(avgLoss) : null,
      countRatio: losses.length ? wins.length / losses.length : null,
      expectancy: expectancy,
      avgHold: holds.length ? mean(holds) : null,
      avgHoldWins: wins.map((t) => t.holdDays).filter(finite).length ? mean(wins.map((t) => t.holdDays).filter(finite)) : null,
      avgHoldLosses: losses.map((t) => t.holdDays).filter(finite).length ? mean(losses.map((t) => t.holdDays).filter(finite)) : null,
      ytdPnl: ytd.length ? ytdPct : null,
      ytdN: ytd.length,
      drawdown: maxDd,
      endingEquity: equity,
      bins: binRows(usable),
    };
  }

  function paperStats(fills, opt) {
    const book = roundTrips(fills);
    const cash0 = opt && finite(Number(opt.startingCash)) ? Number(opt.startingCash) : null;
    let cash = cash0;
    if (cash != null) {
      book.ordered.forEach((f) => {
        if (f.side === "buy") cash -= f.shares * f.price + f.fee;
        else cash += f.shares * f.price - f.fee;
      });
    }
    const prices = (opt && opt.prices) || {};
    let market = 0;
    let valued = 0;
    book.open.forEach((lot) => {
      const px = Number(prices[lot.ticker]);
      if (!pos(px)) return;
      market += lot.shares * px;
      valued += 1;
    });
    const equity = cash != null && valued === book.open.length ? cash + market : null;
    const exposure = equity != null && equity > 0 ? market / equity : null;
    let closed = book.closed;
    if (opt && finite(Number(opt.lossShiftPct)) && Number(opt.lossShiftPct) !== 0) {
      const shift = Number(opt.lossShiftPct);
      closed = closed.map((t) => {
        if (!finite(t.pnlPct) || t.pnlPct >= 0) return t;
        const pnlPct = Math.min(0, t.pnlPct + shift);
        const cost = t.pnlPct !== 0 ? t.pnl / t.pnlPct : 0;
        return Object.assign({}, t, { pnlPct: pnlPct, pnl: cost * pnlPct, shifted: true });
      });
    }
    if (opt && finite(Number(opt.capLossPct))) closed = applyCap(closed, Number(opt.capLossPct));
    const stats = statsFromClosed(closed, { startingCash: cash0, year: opt && opt.year });
    stats.cash = cash;
    stats.market = book.open.length && valued === book.open.length ? market : (book.open.length ? null : 0);
    stats.equity = equity;
    stats.exposure = exposure;
    stats.open = book.open;
    stats.closed = book.closed;
    stats.errors = book.errors;
    stats.groups = groupOpen(book.open, prices);
    stats.stopHint = stopHintFromTrades(book.closed);
    if (cash != null && cash < 0) stats.cashWarning = "Cash is negative. Buys were larger than the starting cash plus sales.";
    return stats;
  }

  function groupOpen(open, prices) {
    const groups = { full: [], half: [], quarter: [], other: [] };
    const by = {};
    open.forEach((lot) => {
      const key = lot.ticker;
      if (!by[key]) by[key] = { ticker: key, shares: 0, cost: 0, fee: 0, stop: lot.stop, size: lot.size || "", date: lot.date };
      by[key].shares += lot.shares;
      by[key].cost += lot.shares * lot.price;
      by[key].fee += lot.feeLeft || 0;
      if (lot.date < by[key].date) by[key].date = lot.date;
      if (pos(lot.stop)) by[key].stop = lot.stop;
      if (lot.size) by[key].size = lot.size;
    });
    Object.keys(by).forEach((k) => {
      const row = by[k];
      row.avg = row.shares > 0 ? (row.cost + row.fee) / row.shares : null;
      const px = Number(prices[k]);
      row.last = pos(px) ? px : null;
      row.pnlPct = row.last != null && row.avg > 0 ? row.last / row.avg - 1 : null;
      row.stopPct = pos(row.stop) && row.avg > 0 ? row.stop / row.avg - 1 : null;
      row.r = row.last != null && pos(row.avg) && pos(row.stop) && row.avg !== row.stop ? (row.last - row.avg) / (row.avg - row.stop) : null;
      const bucket = row.size === "full" || row.size === "half" || row.size === "quarter" ? row.size : "other";
      groups[bucket].push(row);
    });
    return groups;
  }

  function stopHintFromTrades(closed) {
    const last = closed.slice().sort((a, b) => a.exitDate < b.exitDate ? -1 : 1).slice(-20);
    const wins = last.filter((t) => finite(t.pnlPct) && t.pnlPct > 0);
    if (wins.length < 5) {
      return { available: false, reason: "Need at least 5 winning closes among the last 20 closed paper trades. This is not a stop for every stock." };
    }
    const avg = mean(wins.map((t) => t.pnlPct));
    const half = avg / 2;
    return {
      available: true,
      pct: Math.min(half, 0.10),
      avgGain: avg,
      capped: half > 0.10,
      n: wins.length,
      reason: "Half of your average winning gain on those trades, and never above 10%. It describes your log. It is not a stop to copy onto a new stock.",
    };
  }

  function positionSize(input) {
    const equity = Number(input.equity);
    const entry = Number(input.entry);
    const stop = Number(input.stop);
    const riskPct = Number(input.riskPct);
    const fee = input.feePerShare == null || input.feePerShare === "" ? 0 : Number(input.feePerShare);
    if (!pos(equity)) return { ok: false, reason: "Account size must be above zero." };
    if (!pos(entry)) return { ok: false, reason: "Entry must be above zero." };
    if (!pos(stop)) return { ok: false, reason: "Stop must be above zero." };
    if (!finite(riskPct) || riskPct < 0) return { ok: false, reason: "Risk percent is missing." };
    if (riskPct === 0) return { ok: false, reason: "Risk percent is zero, so the share count is not a position." };
    if (!(entry > stop)) return { ok: false, reason: "For a long, the stop has to be below the entry. This calculator does not size shorts." };
    if (!finite(fee) || fee < 0) return { ok: false, reason: "Fee per share cannot be negative." };
    const riskPerShare = entry - stop;
    const dollars = equity * (riskPct / 100);
    const shares = Math.floor(dollars / riskPerShare);
    const warnings = [
      "A 2-to-1 payoff does not set this size. The share count uses only the cash you are willing to lose down to the stop.",
      "A stop does not cap an overnight gap.",
    ];
    if ((entry - stop) / entry > 0.10) warnings.push("The stop is more than 10% under the entry.");
    if (riskPct > 2.5) warnings.push("Risk percent is above 2.5% of the account.");
    const value = shares * entry;
    if (value / equity > 0.25) warnings.push("The position is more than 25% of the account.");
    if (fee > 0) warnings.push("The fee is reported separately and is not subtracted inside the share count.");
    return {
      ok: true,
      shares: shares,
      dollarRisk: shares * riskPerShare,
      fees: shares * fee,
      value: value,
      valuePct: equity > 0 ? value / equity : null,
      warnings: warnings,
    };
  }

  function sbeFraction(input) {
    const entry = Number(input.entry);
    const stop = Number(input.stop);
    const sale = Number(input.sale);
    const shares = Number(input.shares);
    const fee = input.feePerShare == null || input.feePerShare === "" ? 0 : Number(input.feePerShare);
    if (!pos(entry) || !pos(stop) || !pos(sale) || !pos(shares)) return { ok: false, reason: "Entry, stop, sale price, and shares all have to be above zero." };
    if (!(entry > stop)) return { ok: false, reason: "Stop has to be below the entry." };
    if (!(sale > entry)) return { ok: false, reason: "Sale price has to be above the entry. Otherwise the sale does not finance the stop." };
    if (!finite(fee) || fee < 0) return { ok: false, reason: "Fee cannot be negative." };
    const den = sale - stop - fee;
    if (!(den > 0)) return { ok: false, reason: "After the fee, the sale is not far enough above the stop to finance the remainder." };
    const fraction = (entry - stop) / den;
    if (fraction >= 1) return { ok: false, reason: "The fraction is the whole position or more, so a partial sale does not cover the stop on what would remain." };
    return {
      ok: true,
      fraction: fraction,
      sharesToSell: shares * fraction,
      sharesLeft: shares * (1 - fraction),
      assumption: "Our formula: (entry − stop) / (sale − stop − fee per share). It assumes the remaining shares are sold exactly at the stop, with no gap and no later fee.",
    };
  }

  function rbafScenario(input) {
    const size = Number(input.sizePct) / 100;
    const target = Number(input.targetPct) / 100;
    const gain = Number(input.avgGainPct) / 100;
    const loss = Number(input.avgLossPct) / 100;
    const win = Number(input.winPct) / 100;
    const fee = input.feePct == null || input.feePct === "" ? 0 : Number(input.feePct) / 100;
    if (![size, target, gain, loss, win, fee].every(finite)) return { ok: false, reason: "Every input has to be a number." };
    if (!(size > 0 && size <= 1)) return { ok: false, reason: "Position size has to be above 0% and at most 100%." };
    if (!(target > 0)) return { ok: false, reason: "Target has to be above zero." };
    if (!(gain > 0) || !(loss > 0)) return { ok: false, reason: "Average gain and average loss are entered as positive percents." };
    if (!(win >= 0 && win <= 1)) return { ok: false, reason: "Win rate has to be from 0 to 100." };
    if (fee < 0) return { ok: false, reason: "Fee cannot be negative." };
    const edge = win * gain - (1 - win) * loss - fee;
    const r = size * edge;
    if (!(edge > 0) || !(r > 0)) {
      return { ok: false, edge: edge, reason: "The edge is not positive, so a trade count is not defined. A payoff ratio by itself does not create an edge." };
    }
    const linear = target / r;
    const compound = r > -1 ? Math.log(1 + target) / Math.log(1 + r) : null;
    return {
      ok: true,
      edge: edge,
      portfolioEdge: r,
      linearTrades: linear,
      compoundTrades: compound,
      note: "Linear trades match the quoted 25% size, 40% target, 14% gain, 7% loss, 46% win example at about 60. Compounding the same inputs does not, and neither figure is a forecast. There is no variance and no path of losses.",
    };
  }

  function gradeTrade(trade, bars) {
    const notes = [];
    const side = trade.side === "short" ? "short" : "long";
    if (side === "short") notes.push({ tone: "neutral", text: "Short fills are recorded for review only. This desk does not send orders." });
    const entry = Number(trade.entry);
    const exit = trade.exit == null || trade.exit === "" ? null : Number(trade.exit);
    const stop = trade.stop == null || trade.stop === "" ? null : Number(trade.stop);
    const pivot = trade.pivot == null || trade.pivot === "" ? null : Number(trade.pivot);
    if (!pos(entry)) return { notes: [{ tone: "missing", text: "Entry price is missing." }] };
    if (pos(pivot)) {
      const dist = (entry - pivot) / pivot;
      if (Math.abs(dist) <= 0.03) notes.push({ tone: "pos", text: "Entry is within 3% of the pivot you entered." });
      else notes.push({ tone: "neg", text: "Entry is more than 3% away from the pivot you entered." });
    } else notes.push({ tone: "missing", text: "No pivot was entered, so entry versus pivot is blank." });
    if (exit == null) {
      notes.push({ tone: "neutral", text: "Still open, so exit versus plan is not graded." });
    } else if (!pos(exit)) {
      notes.push({ tone: "missing", text: "Exit price is not usable." });
    } else if (side === "long") {
      if (exit > entry) notes.push({ tone: "pos", text: "Exit is above the entry you recorded." });
      else notes.push({ tone: "neg", text: "Exit is not above the entry you recorded." });
      if (pos(stop)) {
        if (!(stop < entry)) notes.push({ tone: "missing", text: "The stop you entered is not below the entry, so loss-versus-plan is blank." });
        else if (exit < entry && exit + 1e-9 >= stop) notes.push({ tone: "pos", text: "The losing exit is at or above the stop you entered." });
        else if (exit < stop) notes.push({ tone: "neg", text: "The exit is below the stop you entered." });
        else notes.push({ tone: "neutral", text: "Exit is above the entry, so the stop was not the exit." });
      } else notes.push({ tone: "missing", text: "No stop was entered." });
    }
    if (pos(stop) && stop < entry && bars && bars.length && trade.entryDate) {
      const end = trade.exitDate || "9999-99-99";
      let peak = entry;
      bars.forEach((b) => {
        if (b.d >= trade.entryDate && b.d <= end && pos(b.h) && b.h > peak) peak = b.h;
      });
      const r = entry - stop;
      if (r > 0 && peak >= entry + 2 * r && exit != null && exit <= entry) {
        notes.push({ tone: "neg", text: "Between the entry date and the exit date you entered, the high reached 2R and the exit was back at or under the entry. This is a review of that window, not a live signal." });
      }
    }
    return { notes: notes };
  }

  function missedResult(row, bars) {
    if (!row || !row.date || !bars || !bars.length) return { available: false, reason: "A date and stored bars are both required." };
    let entry = null;
    for (let i = 0; i < bars.length; i++) if (bars[i].d >= row.date) { entry = bars[i]; break; }
    const last = bars[bars.length - 1];
    if (!entry || !pos(entry.c) || !pos(last.c)) return { available: false, reason: "No stored close on or after that date." };
    if (entry.d === last.d) return { available: false, reason: "The logged date is the latest bar, so there is no later close to measure." };
    return {
      available: true,
      from: entry.d,
      to: last.d,
      pct: last.c / entry.c - 1,
      reason: "Change from the first stored close on or after the date you logged, through the latest stored close. It is not a signal result and it was not known on that date.",
    };
  }

  return {
    MA_PERIODS: MA_PERIODS,
    MA_COLORS: MA_COLORS,
    ENTRY_COLOR: ENTRY_COLOR,
    STOP_COLOR: STOP_COLOR,
    TARGET_COLOR: TARGET_COLOR,
    PIVOT_COLOR: PIVOT_COLOR,
    RS_WEIGHTS: RS_WEIGHTS,
    SCREEN_DEFS: SCREEN_DEFS,
    COVERAGE: COVERAGE,
    parseBars: parseBars,
    analyzeBars: analyzeBars,
    percentileRanks: percentileRanks,
    calendar: calendar,
    rankDates: rankDates,
    gradeAt: gradeAt,
    stageAt: stageAt,
    templateAt: templateAt,
    eventsAt: eventsAt,
    netOf: netOf,
    finalizeStock: finalizeStock,
    buildDesk: buildDesk,
    regimeFromMarket: regimeFromMarket,
    summarize: summarize,
    toWeekly: toWeekly,
    weekMonday: weekMonday,
    roundTrips: roundTrips,
    paperStats: paperStats,
    binRows: binRows,
    stopHintFromTrades: stopHintFromTrades,
    positionSize: positionSize,
    sbeFraction: sbeFraction,
    rbafScenario: rbafScenario,
    gradeTrade: gradeTrade,
    missedResult: missedResult,
    smaSeries: smaSeries,
    finite: finite,
    round: round,
  };
});
