// Flowchart layout: the AI only lists nodes and arrows; this file decides where everything goes.
// Pure (no browser code) so it can be unit-tested.
const GAP_MAIN = 56;     // space between levels
const GAP_CROSS = 28;    // space between boxes on the same level
const PAD = 14;

function nodeSize(label, shape) {
  const w = Math.min(220, Math.max(90, label.length * 8.6 + 28));
  return { w: shape === "diamond" ? w + 30 : w, h: shape === "diamond" ? 66 : 44 };
}

// Levels: how far each node is from the start. Arrows pointing back (loops) are ignored for levelling.
function levelsOf(ids, edges) {
  const out = new Map(ids.map((id) => [id, []]));
  const indeg = new Map(ids.map((id) => [id, 0]));
  for (const [a, b] of edges) { out.get(a).push(b); indeg.set(b, indeg.get(b) + 1); }
  const level = new Map(), state = new Map();
  const visit = (id, depth) => {
    if (state.get(id) === 1) return;                      // loop: stop here
    level.set(id, Math.max(level.get(id) ?? 0, depth));
    state.set(id, 1);
    for (const next of out.get(id)) visit(next, depth + 1);
    state.set(id, 0);
  };
  const roots = ids.filter((id) => indeg.get(id) === 0);
  (roots.length ? roots : [ids[0]]).forEach((id) => visit(id, 0));
  ids.forEach((id) => { if (!level.has(id)) visit(id, 0); });
  return level;
}

// nodes: [[id, label, shape]], edges: [[from, to, label]], dir: "down" | "right"
export function layoutFlow(nodes, edges, dir = "down") {
  const down = dir !== "right";
  const items = nodes.map(([id, label, shape]) => ({ id, label, shape, ...nodeSize(label, shape) }));
  const byId = new Map(items.map((n) => [n.id, n]));
  const level = levelsOf(items.map((n) => n.id), edges);

  const rows = [];
  for (const n of items) (rows[level.get(n.id)] ??= []).push(n);
  const levels = rows.filter(Boolean);

  // size of each level along the "cross" direction, and the thickness along the "main" direction
  const cross = (n) => (down ? n.w : n.h), main = (n) => (down ? n.h : n.w);
  const spans = levels.map((row) => row.reduce((s, n) => s + cross(n), 0) + GAP_CROSS * (row.length - 1));
  const widest = Math.max(...spans);
  const thick = levels.map((row) => Math.max(...row.map(main)));

  let at = PAD;
  levels.forEach((row, li) => {
    let c = PAD + (widest - spans[li]) / 2;
    for (const n of row) {
      const mainPos = at + (thick[li] - main(n)) / 2;
      n.x = down ? c : mainPos;
      n.y = down ? mainPos : c;
      c += cross(n) + GAP_CROSS;
    }
    at += thick[li] + GAP_MAIN;
  });
  const total = at - GAP_MAIN + PAD;
  const w = down ? widest + 2 * PAD : total, h = down ? total : widest + 2 * PAD;

  const arrows = edges.map(([a, b, label]) => {
    const from = byId.get(a), to = byId.get(b);
    const fc = { x: from.x + from.w / 2, y: from.y + from.h / 2 }, tc = { x: to.x + to.w / 2, y: to.y + to.h / 2 };
    const backwards = down ? tc.y <= fc.y : tc.x <= fc.x;
    const p1 = down ? { x: fc.x, y: backwards ? from.y : from.y + from.h } : { x: backwards ? from.x : from.x + from.w, y: fc.y };
    const p2 = down ? { x: tc.x, y: backwards ? to.y + to.h : to.y } : { x: backwards ? to.x + to.w : to.x, y: tc.y };
    return { from: p1, to: p2, label: label || "" };
  });
  return { w, h, nodes: items, arrows };
}
