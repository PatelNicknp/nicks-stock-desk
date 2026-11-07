/* Canvas chart for Nick 360. Bars and averages are passed in. No network. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.N360Chart = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const COL = { 10: "#22c55e", 20: "#f97316", 50: "#3b82f6", 150: "#eab308", 200: "#ef4444" };
  const GRADE = { A: "#15803d", B: "#22c55e", C: "#eab308", D: "#ef4444" };
  const BAND = { green: "#15803d", yellow: "#a16207", red: "#b91c1c" };

  function finite(n) { return typeof n === "number" && Number.isFinite(n); }
  function viewCount(range, n) {
    if (range === "1M") return Math.min(n, 21);
    if (range === "3M") return Math.min(n, 63);
    if (range === "6M") return Math.min(n, 126);
    if (range === "5Y") return n;
    return Math.min(n, 252);
  }

  function drawChart(canvas, stock, opt) {
    const o = opt || {};
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(rect.width || canvas.clientWidth || 0, 280);
    const h = Math.max(rect.height || canvas.clientHeight || 0, 280);
    canvas.width = Math.max(1, Math.floor(w * dpr));
    canvas.height = Math.max(1, Math.floor(h * dpr));
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#12151d";
    ctx.fillRect(0, 0, w, h);
    const bars = stock && stock.bars ? stock.bars : [];
    if (!bars.length) {
      ctx.fillStyle = "#8a90a2";
      ctx.font = "13px Segoe UI, sans-serif";
      ctx.fillText("No stored daily bars for this symbol.", 16, 32);
      return { indexAt: function () { return null; } };
    }
    const count = viewCount(o.range || "1Y", bars.length);
    const start = bars.length - count;
    const right = 62;
    const left = 8;
    const plotW = Math.max(10, w - right - left);
    const strip = 12;
    const stripsTop = 6;
    const netTop = stripsTop + strip * 3 + 8;
    const head = netTop + 18;
    let volH = Math.max(48, Math.round(h * 0.12));
    let rankH = Math.max(44, Math.round(h * 0.09));
    const bottom = 16;
    const priceTop = head + 28;
    let priceBot = h - bottom - rankH - volH;
    if (priceBot - priceTop < 180) {
      volH = 56;
      rankH = 48;
      priceBot = h - bottom - rankH - volH;
    }
    const bw = plotW / count;
    function xAt(i) { return left + (i - start) * bw; }
    function colorOf(v) { return BAND[v] || "#1c2130"; }

    function stripRow(name, y, paint) {
      for (let i = start; i < bars.length; i++) {
        ctx.fillStyle = paint(i);
        ctx.fillRect(xAt(i), y, bw + 0.6, strip);
      }
      ctx.fillStyle = "rgba(10,12,18,.72)";
      ctx.fillRect(left + 2, y + 1, ctx.measureText(name).width + 8, strip - 2);
      ctx.fillStyle = "#e6e8ee";
      ctx.font = "10px Segoe UI, sans-serif";
      ctx.fillText(name, left + 6, y + strip - 3);
    }
    ctx.font = "10px Segoe UI, sans-serif";
    stripRow("Pressure", stripsTop, (i) => stock.pressure[i] ? colorOf(stock.pressure[i].color) : "#1c2130");
    stripRow("Entry risk", stripsTop + strip + 2, (i) => stock.risk[i] ? colorOf(stock.risk[i].color) : "#1c2130");
    stripRow("Grade", stripsTop + (strip + 2) * 2, (i) => {
      const g = stock.grade[i];
      return g && g.letter ? GRADE[g.letter] : "#1c2130";
    });

    ctx.fillStyle = "#8a90a2";
    ctx.fillText("Alert net", left + 6, netTop + 12);
    for (let i = start; i < bars.length; i++) {
      const ev = (stock.recent || []).find((r) => r.index === i);
      const net = ev ? ev.net : 0;
      if (!net) continue;
      const hh = Math.min(8, Math.abs(net) * 2);
      ctx.fillStyle = net > 0 ? "#22c55e" : "#ef4444";
      ctx.fillRect(xAt(i), net > 0 ? netTop + 10 - hh : netTop + 10, Math.max(1, bw * 0.7), hh);
    }

    let lo = Infinity;
    let hi = -Infinity;
    function take(v) { if (finite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } }
    for (let i = start; i < bars.length; i++) {
      take(bars[i].h); take(bars[i].l);
      [10, 20, 50, 150, 200].forEach((p) => take(stock.sma[p][i]));
    }
    const span = hi - lo;
    (o.levels || []).forEach((lv) => {
      if (!finite(lv.price) || !finite(span)) return;
      if (lv.price >= lo - span * 0.25 && lv.price <= hi + span * 0.25) take(lv.price);
    });
    if (!finite(lo) || !finite(hi) || lo === hi) { lo = bars[bars.length - 1].c * 0.95; hi = bars[bars.length - 1].c * 1.05; }
    const pad = (hi - lo) * 0.06;
    lo -= pad; hi += pad;
    function yPrice(v) { return priceTop + (hi - v) / (hi - lo) * (priceBot - priceTop); }

    ctx.strokeStyle = "#1c2130";
    ctx.lineWidth = 1;
    ctx.font = "11px Segoe UI, sans-serif";
    ctx.fillStyle = "#7d8396";
    for (let k = 0; k <= 4; k++) {
      const p = lo + (hi - lo) * k / 4;
      const y = yPrice(p);
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(w - right, y);
      ctx.stroke();
      ctx.fillText(p >= 100 ? p.toFixed(0) : p.toFixed(2), w - right + 4, y + 3);
    }

    (o.levels || []).forEach((lv) => {
      if (!finite(lv.price)) return;
      ctx.strokeStyle = lv.color;
      ctx.setLineDash([4, 3]);
      const y = yPrice(lv.price);
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(w - right, y);
      ctx.stroke();
      ctx.setLineDash([]);
    });

    [200, 150, 50, 20, 10].forEach((p) => {
      ctx.strokeStyle = COL[p];
      ctx.lineWidth = p === 50 || p === 200 ? 1.7 : 1.15;
      ctx.beginPath();
      let moved = false;
      for (let i = start; i < bars.length; i++) {
        const v = stock.sma[p][i];
        if (!finite(v)) continue;
        const x = xAt(i) + bw / 2;
        if (!moved) { ctx.moveTo(x, yPrice(v)); moved = true; }
        else ctx.lineTo(x, yPrice(v));
      }
      ctx.stroke();
    });
    ctx.lineWidth = 1;

    for (let i = start; i < bars.length; i++) {
      const b = bars[i];
      const x = xAt(i) + bw / 2;
      const up = b.c >= b.o;
      ctx.strokeStyle = ctx.fillStyle = up ? "#22c55e" : "#ef4444";
      ctx.beginPath();
      ctx.moveTo(x, yPrice(b.h));
      ctx.lineTo(x, yPrice(b.l));
      ctx.stroke();
      const y1 = yPrice(Math.max(b.o, b.c));
      const y2 = yPrice(Math.min(b.o, b.c));
      ctx.fillRect(x - Math.max(1, bw * 0.32), y1, Math.max(1, bw * 0.64), Math.max(1, y2 - y1));
    }

    (o.marks || []).forEach((m) => {
      const i = bars.findIndex((b) => b.d >= m.date);
      if (i < start || i < 0) return;
      const x = xAt(i) + bw / 2;
      const y = yPrice(bars[i].l) + 12;
      ctx.fillStyle = m.color || "#22c55e";
      ctx.beginPath();
      ctx.moveTo(x, y - 8);
      ctx.lineTo(x - 5, y);
      ctx.lineTo(x + 5, y);
      ctx.fill();
      ctx.font = "10px Segoe UI, sans-serif";
      ctx.fillText(m.text, x + 6, y);
    });

    const last = bars[bars.length - 1];
    function tag(price, color, text) {
      if (!finite(price)) return;
      const y = yPrice(price);
      ctx.fillStyle = color;
      const tw = ctx.measureText(text).width + 8;
      ctx.fillRect(w - right + 2, y - 8, Math.max(tw, right - 6), 16);
      ctx.fillStyle = "#fff";
      ctx.fillText(text, w - right + 6, y + 4);
    }
    ctx.font = "10px Segoe UI, sans-serif";
    tag(last.c, last.c >= bars[Math.max(0, bars.length - 2)].c ? "#15803d" : "#b91c1c", last.c.toFixed(2));
    [10, 20, 50].forEach((p) => {
      const v = stock.sma[p][bars.length - 1];
      if (finite(v)) tag(v, COL[p], v.toFixed(2));
    });

    ctx.fillStyle = "#e6e8ee";
    ctx.font = "12px Segoe UI, sans-serif";
    const title = (stock.ticker || "") + (stock.company ? " · " + stock.company : "") + (o.weekly ? " · 1W from daily bars" : " · 1D");
    ctx.fillText(title, left + 4, priceTop - 16);
    let lx = left + 4;
    ctx.font = "11px Segoe UI, sans-serif";
    [10, 20, 50, 150, 200].forEach((p) => {
      const v = stock.sma[p][bars.length - 1];
      if (!finite(v)) return;
      const text = "MA" + p + " " + v.toFixed(2);
      ctx.fillStyle = COL[p];
      ctx.fillText(text, lx, priceTop - 4);
      lx += ctx.measureText(text).width + 10;
    });

    const vTop = priceBot + 2;
    const vBot = priceBot + volH - 4;
    let vmax = 0;
    for (let i = start; i < bars.length; i++) if (finite(bars[i].v) && bars[i].v > vmax) vmax = bars[i].v;
    ctx.fillStyle = "#7d8396";
    ctx.fillText("Volume", left + 4, vTop + 11);
    if (vmax > 0) {
      for (let i = start; i < bars.length; i++) {
        if (!finite(bars[i].v)) continue;
        const hh = bars[i].v / vmax * (vBot - vTop - 14);
        ctx.fillStyle = bars[i].c >= bars[i].o ? "rgba(34,197,94,.7)" : "rgba(239,68,68,.7)";
        ctx.fillRect(xAt(i) + bw * 0.15, vBot - hh, Math.max(1, bw * 0.7), hh);
      }
    }

    const rTop = vBot + 8;
    const rBot = h - bottom;
    ctx.strokeStyle = "#262b38";
    ctx.beginPath();
    ctx.moveTo(0, rTop);
    ctx.lineTo(w, rTop);
    ctx.stroke();
    ctx.fillStyle = "#7d8396";
    const lastRank = stock.rank[bars.length - 1];
    ctx.fillText("Rank 1–99" + (finite(lastRank) ? "  " + lastRank : "  unavailable"), left + 4, rTop + 12);
    ctx.strokeStyle = "#3b82f6";
    ctx.beginPath();
    let moved = false;
    for (let i = start; i < bars.length; i++) {
      if (!finite(stock.rank[i])) continue;
      const x = xAt(i) + bw / 2;
      const y = rBot - (stock.rank[i] / 99) * (rBot - rTop - 16);
      if (!moved) { ctx.moveTo(x, y); moved = true; }
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([2, 3]);
    ctx.strokeStyle = "#3a4052";
    const y70 = rBot - (70 / 99) * (rBot - rTop - 16);
    ctx.beginPath();
    ctx.moveTo(left, y70);
    ctx.lineTo(w - right, y70);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = "#7d8396";
    ctx.font = "10px Segoe UI, sans-serif";
    for (let i = start; i < bars.length; i += Math.max(1, Math.floor(count / 6))) {
      ctx.fillText(bars[i].d.slice(2, 7), xAt(i), h - 4);
    }

    if (finite(o.hover) && o.hover >= start && o.hover < bars.length) {
      const x = xAt(o.hover) + bw / 2;
      ctx.strokeStyle = "rgba(200,200,220,.45)";
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#2b2850";
      const label = bars[o.hover].d;
      ctx.fillRect(Math.min(w - 78, x + 4), 4, 72, 16);
      ctx.fillStyle = "#ddd8ff";
      ctx.fillText(label, Math.min(w - 74, x + 8), 15);
    }

    return {
      indexAt: function (px) {
        if (px < left || px > left + plotW) return null;
        const i = start + Math.floor((px - left) / bw);
        if (i < start || i >= bars.length) return null;
        return i;
      },
    };
  }

  function drawBars(canvas, rows) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 300;
    const h = canvas.clientHeight || 140;
    canvas.width = Math.max(1, Math.floor(w * dpr));
    canvas.height = Math.max(1, Math.floor(h * dpr));
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!rows.length) {
      ctx.fillStyle = "#8a90a2";
      ctx.font = "12px Segoe UI, sans-serif";
      ctx.fillText("No closed paper trades yet.", 8, 24);
      return;
    }
    let max = 0;
    rows.forEach((r) => { if (Math.abs(r.v) > max) max = Math.abs(r.v); });
    if (max === 0) max = 1;
    const base = rows.some((r) => r.v < 0) ? h * 0.62 : h - 8;
    ctx.strokeStyle = "#2a3042";
    ctx.beginPath();
    ctx.moveTo(0, base);
    ctx.lineTo(w, base);
    ctx.stroke();
    const bw = w / rows.length;
    rows.forEach((r, i) => {
      const hh = Math.abs(r.v) / max * (r.v >= 0 ? base - 6 : h - base - 4);
      ctx.fillStyle = r.color;
      ctx.fillRect(i * bw + bw * 0.18, r.v >= 0 ? base - hh : base, Math.max(1, bw * 0.64), Math.max(1, hh));
    });
  }

  return { drawChart: drawChart, drawBars: drawBars, viewCount: viewCount };
});
