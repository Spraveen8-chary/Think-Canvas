// Draws the AI's visual blocks on the canvas: plot, chart, flow, draw, anim.
// Each block arrives as a small JSON "spec" (validated by the backend); here it becomes pixels.
import { compile } from "./mathexpr.js";
import { layoutFlow } from "./flow.js";

const INK = "#1f2430", BLUE = "#2447d6", MUTED = "#8a91a6";
const PALETTE = ["#2447d6", "#e0562b", "#1e8e5a", "#9b51e0", "#d4a017", "#17a2b8"];
const FONT = '13px system-ui, "Segoe UI", sans-serif';

// ---- sizes (so the board can place a block before drawing it) ----------------------------
export function makeBlockItem(block) {
  switch (block.t) {
    case "plot": return { type: "plot", spec: block, w: 380, h: 280 };
    case "chart": return { type: "chart", spec: block, w: 380, h: 270 };
    case "flow": {
      const lay = layoutFlow(block.nodes, block.edges, block.dir);
      const k = Math.min(1, 640 / lay.w, 640 / lay.h);
      return { type: "flow", spec: block, w: Math.ceil(lay.w * k), h: Math.ceil(lay.h * k), k };
    }
    case "draw": return { type: "draw", spec: block, w: block.w, h: block.h };
    case "anim": return { type: "anim", spec: block, w: block.w, h: block.h };
    default: return null;
  }
}

export const isVisualType = (type) => ["plot", "chart", "flow", "draw", "anim"].includes(type);

function card(g, item) {
  g.fillStyle = "rgba(36,71,214,.04)";
  g.strokeStyle = "rgba(36,71,214,.25)";
  g.lineWidth = 1;
  g.beginPath();
  g.roundRect ? g.roundRect(item.x, item.y, item.w, item.h, 10) : g.rect(item.x, item.y, item.w, item.h);
  g.fill();
  g.stroke();
}

function arrowHead(g, x1, y1, x2, y2, size = 9) {
  const a = Math.atan2(y2 - y1, x2 - x1);
  g.beginPath();
  g.moveTo(x2, y2);
  g.lineTo(x2 - size * Math.cos(a - 0.4), y2 - size * Math.sin(a - 0.4));
  g.lineTo(x2 - size * Math.cos(a + 0.4), y2 - size * Math.sin(a + 0.4));
  g.closePath();
  g.fill();
}

function niceStep(range, target = 5) {
  const raw = range / target, mag = 10 ** Math.floor(Math.log10(raw)), n = raw / mag;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * mag;
}
const fmt = (v) => (Math.abs(v) >= 1000 || (v !== 0 && Math.abs(v) < 0.01) ? v.toExponential(0) : String(Math.round(v * 1000) / 1000));

// ---- plot --------------------------------------------------------------------------------
function paintPlot(g, item) {
  card(g, item);
  const { f, x: [x0, x1], y } = item.spec;
  const L = item.x + 40, R = item.x + item.w - 14, T = item.y + 24, B = item.y + item.h - 28;
  const fns = f.map((src) => { try { return { src, fn: compile(src) }; } catch { return null; } }).filter(Boolean);
  g.font = FONT; g.textBaseline = "middle";
  if (!fns.length) { g.fillStyle = MUTED; g.fillText("Cannot plot this formula", item.x + 14, item.y + item.h / 2); return; }

  const N = 260, samples = fns.map(({ fn }) => Array.from({ length: N + 1 }, (_, i) => { const xv = x0 + ((x1 - x0) * i) / N; return [xv, fn(xv)]; }));
  let y0, y1;
  if (y) [y0, y1] = y;
  else {
    const vals = samples.flat().map((p) => p[1]).filter((v) => Number.isFinite(v) && Math.abs(v) < 1e6).sort((a, b) => a - b);
    if (!vals.length) { g.fillStyle = MUTED; g.fillText("Nothing to plot in this range", item.x + 14, item.y + item.h / 2); return; }
    const lo = vals[Math.floor(vals.length * 0.02)], hi = vals[Math.ceil(vals.length * 0.98) - 1];
    const pad = (hi - lo || 1) * 0.12;
    [y0, y1] = [lo - pad, hi + pad];
  }
  const sx = (v) => L + ((v - x0) / (x1 - x0)) * (R - L), sy = (v) => B - ((v - y0) / (y1 - y0)) * (B - T);

  g.lineWidth = 1; g.fillStyle = MUTED; g.textAlign = "center";
  const stepX = niceStep(x1 - x0), stepY = niceStep(y1 - y0);
  for (let v = Math.ceil(x0 / stepX) * stepX; v <= x1; v += stepX) {
    g.strokeStyle = "#e3e6ef"; g.beginPath(); g.moveTo(sx(v), T); g.lineTo(sx(v), B); g.stroke();
    g.fillText(fmt(v), sx(v), B + 14);
  }
  g.textAlign = "right";
  for (let v = Math.ceil(y0 / stepY) * stepY; v <= y1; v += stepY) {
    g.strokeStyle = "#e3e6ef"; g.beginPath(); g.moveTo(L, sy(v)); g.lineTo(R, sy(v)); g.stroke();
    g.fillText(fmt(v), L - 5, sy(v));
  }
  g.strokeStyle = INK; g.lineWidth = 1.4;                       // axes through zero when visible
  if (x0 <= 0 && x1 >= 0) { g.beginPath(); g.moveTo(sx(0), T); g.lineTo(sx(0), B); g.stroke(); }
  if (y0 <= 0 && y1 >= 0) { g.beginPath(); g.moveTo(L, sy(0)); g.lineTo(R, sy(0)); g.stroke(); }

  g.save();
  g.beginPath(); g.rect(L, T, R - L, B - T); g.clip();
  samples.forEach((pts, i) => {
    g.strokeStyle = PALETTE[i % PALETTE.length]; g.lineWidth = 2.2; g.beginPath();
    let pen = false, prev = null;
    for (const [xv, yv] of pts) {
      if (!Number.isFinite(yv) || Math.abs(yv) > 1e6 || (prev !== null && Math.abs(yv - prev) > (y1 - y0) * 3)) { pen = false; prev = Number.isFinite(yv) ? yv : null; continue; }
      pen ? g.lineTo(sx(xv), sy(yv)) : g.moveTo(sx(xv), sy(yv));
      pen = true; prev = yv;
    }
    g.stroke();
  });
  g.restore();
  g.textAlign = "left";                                         // legend, one entry after another
  let lx = item.x + 12;
  fns.forEach(({ src }, i) => {
    const label = `y = ${src}`;
    g.fillStyle = PALETTE[i % PALETTE.length];
    g.fillText(label, lx, item.y + 12);
    lx += g.measureText(label).width + 16;
  });
}

// ---- chart -------------------------------------------------------------------------------
function paintChart(g, item) {
  card(g, item);
  const { kind, labels, values, title } = item.spec;
  g.font = FONT; g.textBaseline = "middle"; g.textAlign = "center"; g.fillStyle = INK;
  if (title) { g.font = `600 ${FONT}`; g.fillText(title, item.x + item.w / 2, item.y + 16); g.font = FONT; }
  const top = item.y + (title ? 34 : 18), bottom = item.y + item.h - 30, left = item.x + 40, right = item.x + item.w - 14;

  if (kind === "pie") {
    const total = values.reduce((s, v) => s + v, 0) || 1;
    const cx = item.x + item.w * 0.36, cy = (top + item.y + item.h) / 2, r = Math.min(item.w * 0.3, (item.h - (title ? 50 : 30)) / 2);
    let a = -Math.PI / 2;
    values.forEach((v, i) => {
      const da = (v / total) * Math.PI * 2;
      g.fillStyle = PALETTE[i % PALETTE.length]; g.beginPath(); g.moveTo(cx, cy); g.arc(cx, cy, r, a, a + da); g.closePath(); g.fill();
      a += da;
    });
    g.textAlign = "left";
    labels.forEach((l, i) => {
      const ly = top + 8 + i * 18;
      g.fillStyle = PALETTE[i % PALETTE.length]; g.fillRect(item.x + item.w * 0.68, ly - 5, 10, 10);
      g.fillStyle = INK; g.fillText(`${l} (${Math.round((values[i] / total) * 100)}%)`, item.x + item.w * 0.68 + 15, ly);
    });
    return;
  }
  const max = Math.max(...values, 0), min = Math.min(...values, 0), span = max - min || 1;
  const sy = (v) => bottom - ((v - min) / span) * (bottom - top);
  g.strokeStyle = "#e3e6ef"; g.fillStyle = MUTED; g.textAlign = "right";
  const step = niceStep(span, 4);
  for (let v = Math.ceil(min / step) * step; v <= max; v += step) { g.beginPath(); g.moveTo(left, sy(v)); g.lineTo(right, sy(v)); g.stroke(); g.fillText(fmt(v), left - 5, sy(v)); }
  const slot = (right - left) / values.length;
  g.textAlign = "center";
  if (kind === "line") { g.strokeStyle = PALETTE[0]; g.lineWidth = 2.4; g.beginPath(); }
  values.forEach((v, i) => {
    const cx = left + slot * (i + 0.5);
    if (kind === "bar") { g.fillStyle = PALETTE[i % PALETTE.length]; g.fillRect(cx - slot * 0.3, Math.min(sy(v), sy(0)), slot * 0.6, Math.abs(sy(v) - sy(0))); }
    else { i ? g.lineTo(cx, sy(v)) : g.moveTo(cx, sy(v)); }
    g.fillStyle = MUTED; g.fillText(labels[i].slice(0, Math.max(3, Math.floor(slot / 7))), cx, bottom + 14);
  });
  if (kind === "line") {
    g.stroke();
    g.fillStyle = PALETTE[0];
    values.forEach((v, i) => { g.beginPath(); g.arc(left + slot * (i + 0.5), sy(v), 3.5, 0, Math.PI * 2); g.fill(); });
  }
}

// ---- flowchart ---------------------------------------------------------------------------
function paintFlow(g, item) {
  const lay = layoutFlow(item.spec.nodes, item.spec.edges, item.spec.dir);
  card(g, item);
  g.save();
  g.translate(item.x, item.y); g.scale(item.k, item.k);
  g.font = "14px system-ui, 'Segoe UI', sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
  g.strokeStyle = INK; g.fillStyle = INK; g.lineWidth = 1.6;
  for (const a of lay.arrows) {
    g.beginPath(); g.moveTo(a.from.x, a.from.y); g.lineTo(a.to.x, a.to.y); g.stroke();
    arrowHead(g, a.from.x, a.from.y, a.to.x, a.to.y);
    if (a.label) {
      const mx = (a.from.x + a.to.x) / 2, my = (a.from.y + a.to.y) / 2, tw = g.measureText(a.label).width + 8;
      g.fillStyle = "#fff"; g.fillRect(mx - tw / 2, my - 9, tw, 18);
      g.fillStyle = BLUE; g.fillText(a.label, mx, my);
      g.fillStyle = INK;
    }
  }
  for (const n of lay.nodes) {
    const cx = n.x + n.w / 2, cy = n.y + n.h / 2;
    g.fillStyle = "#fff"; g.strokeStyle = BLUE; g.lineWidth = 1.8;
    g.beginPath();
    if (n.shape === "diamond") { g.moveTo(cx, n.y); g.lineTo(n.x + n.w, cy); g.lineTo(cx, n.y + n.h); g.lineTo(n.x, cy); g.closePath(); }
    else if (n.shape === "oval") g.ellipse(cx, cy, n.w / 2, n.h / 2, 0, 0, Math.PI * 2);
    else g.roundRect ? g.roundRect(n.x, n.y, n.w, n.h, 8) : g.rect(n.x, n.y, n.w, n.h);
    g.fill(); g.stroke();
    g.fillStyle = INK; g.fillText(n.label.slice(0, 36), cx, cy, n.w - 14);
  }
  g.restore();
}

// ---- free drawing (shapes) -----------------------------------------------------------------
function paintDraw(g, item) {
  card(g, item);
  g.save();
  g.beginPath(); g.rect(item.x, item.y, item.w, item.h); g.clip();
  g.translate(item.x, item.y);
  g.strokeStyle = INK; g.fillStyle = INK; g.lineWidth = 2; g.lineCap = "round"; g.font = "14px system-ui, sans-serif";
  g.textBaseline = "middle"; g.textAlign = "left";
  for (const [kind, ...a] of item.spec.s) {
    g.beginPath();
    if (kind === "line" || kind === "arrow") { g.moveTo(a[0], a[1]); g.lineTo(a[2], a[3]); g.stroke(); if (kind === "arrow") arrowHead(g, a[0], a[1], a[2], a[3]); }
    else if (kind === "rect") g.strokeRect(a[0], a[1], a[2], a[3]);
    else if (kind === "circle") { g.arc(a[0], a[1], Math.max(0, a[2]), 0, Math.PI * 2); g.stroke(); }
    else if (kind === "ellipse") { g.ellipse(a[0], a[1], Math.max(0, a[2]), Math.max(0, a[3]), 0, 0, Math.PI * 2); g.stroke(); }
    else if (kind === "text") g.fillText(a[2], a[0], a[1]);
  }
  g.restore();
}

// ---- animation (declarative: the AI never sends code) ---------------------------------------
const anchorOf = (o) => (o.type === "circle" ? [o.cx, o.cy] : o.type === "rect" ? [o.x + o.w / 2, o.y + o.h / 2] : o.type === "line" ? [(o.x1 + o.x2) / 2, (o.y1 + o.y2) / 2] : [o.x, o.y]);

// Position/rotation/scale of every object at time `t` (ms). Exported for tests.
export function sceneState(spec, t) {
  const base = new Map(spec.o.map((o) => [o.id, anchorOf(o)]));
  const st = new Map(spec.o.map((o) => [o.id, { dx: 0, dy: 0, rot: 0, scale: 1 }]));
  for (const m of spec.m) {
    const s = st.get(m.target), [ax, ay] = base.get(m.target), phase = ((t % m.ms) / m.ms);
    if (m.type === "orbit") {
      const [cx, cy] = Array.isArray(m.center) ? m.center : base.get(m.center);
      const a0 = Math.atan2((ay - cy) / m.ry, (ax - cx) / m.rx), a = a0 + phase * Math.PI * 2;
      s.dx = cx + m.rx * Math.cos(a) - ax; s.dy = cy + m.ry * Math.sin(a) - ay;
    } else if (m.type === "spin") s.rot = phase * Math.PI * 2;
    else if (m.type === "move") {
      const p = phase < 0.5 ? phase * 2 : 2 - phase * 2;           // there and back
      s.dx = m.from[0] + (m.to[0] - m.from[0]) * p - ax; s.dy = m.from[1] + (m.to[1] - m.from[1]) * p - ay;
    } else if (m.type === "pulse") s.scale = m.from + (m.to - m.from) * (0.5 - 0.5 * Math.cos(phase * Math.PI * 2));
  }
  return { base, st };
}

function paintAnim(g, item, now) {
  card(g, item);
  const { base, st } = sceneState(item.spec, now);
  g.save();
  g.beginPath(); g.rect(item.x, item.y, item.w, item.h); g.clip();
  g.translate(item.x, item.y);
  for (const o of item.spec.o) {
    const s = st.get(o.id), [ax, ay] = base.get(o.id);
    g.save();
    g.translate(ax + s.dx, ay + s.dy); g.rotate(s.rot); g.scale(s.scale, s.scale); g.translate(-ax, -ay);
    g.fillStyle = o.fill || "transparent"; g.strokeStyle = o.stroke || (o.fill ? "transparent" : INK); g.lineWidth = 2;
    g.beginPath();
    if (o.type === "circle") g.arc(o.cx, o.cy, Math.max(0, o.r), 0, Math.PI * 2);
    else if (o.type === "rect") g.rect(o.x, o.y, o.w, o.h);
    else if (o.type === "line") { g.moveTo(o.x1, o.y1); g.lineTo(o.x2, o.y2); g.strokeStyle = o.stroke || o.fill || INK; }
    if (o.type !== "text") { g.fill(); g.stroke(); }
    else { g.fillStyle = o.fill || INK; g.font = `${o.size}px system-ui, sans-serif`; g.textBaseline = "middle"; g.fillText(o.text, o.x, o.y); }
    g.restore();
  }
  g.restore();
}

export function paintBlock(g, item, now = 0) {
  switch (item.type) {
    case "plot": return paintPlot(g, item);
    case "chart": return paintChart(g, item);
    case "flow": return paintFlow(g, item);
    case "draw": return paintDraw(g, item);
    case "anim": return paintAnim(g, item, now);
  }
}
