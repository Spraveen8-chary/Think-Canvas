// Pure geometry helpers (no browser code), so they can be unit-tested in Node.
// A "box" is { x, y, w, h } in canvas (world) coordinates.

export function pointsBounds(points) {
  let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
  for (const [x, y] of points) {
    if (x < x1) x1 = x; if (y < y1) y1 = y;
    if (x > x2) x2 = x; if (y > y2) y2 = y;
  }
  return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
}

export const union = (a, b) => {
  if (!a) return b;
  const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y);
  return { x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y };
};

export const grow = (b, p) => ({ x: b.x - p, y: b.y - p, w: b.w + 2 * p, h: b.h + 2 * p });

export const intersects = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

export const contains = (b, [x, y]) => x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h;

export function distToSegment([px, py], [ax, ay], [bx, by]) {
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2)) : 0;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

// Where to put an answer box of `size` {w,h} next to the writing `box`.
// Prefers: right of the writing, then below it, then left of it; must be inside `view`
// and must not overlap `taken` boxes (earlier answers). Otherwise slides down until free.
export function placeAnswer(box, size, view, taken = [], gap = 28) {
  const spots = [
    { x: box.x + box.w + gap, y: box.y },
    { x: box.x, y: box.y + box.h + gap },
    { x: box.x - gap - size.w, y: box.y },
  ];
  const rect = (s) => ({ x: s.x, y: s.y, w: size.w, h: size.h });
  const free = (s) => !taken.some((t) => intersects(t, rect(s)));
  const visible = (s) => s.x >= view.x && s.y >= view.y && s.x + size.w <= view.x + view.w && s.y + size.h <= view.y + view.h;

  const good = spots.find((s) => free(s) && visible(s));
  if (good) return good;
  const spot = { ...spots[1] };
  while (!free(spot)) spot.y += size.h + 12;
  return spot;
}

// Splits text into lines no wider than maxWidth. `measure(text)` returns pixel width.
export function wrapText(text, maxWidth, measure) {
  const lines = [];
  for (const para of String(text).split("\n")) {
    let line = "";
    for (const word of para.split(/\s+/).filter(Boolean)) {
      const next = line ? `${line} ${word}` : word;
      if (measure(next) <= maxWidth) { line = next; continue; }
      if (line) lines.push(line);
      line = word;
      while (measure(line) > maxWidth && line.length > 1) {   // a single very long word
        let n = line.length - 1;
        while (n > 1 && measure(line.slice(0, n)) > maxWidth) n--;
        lines.push(line.slice(0, n));
        line = line.slice(n);
      }
    }
    lines.push(line);
  }
  return lines;
}

// Groups boxes that are close to each other (within `gap`) into "spots" of work.
// Returns [{ box, last }] where `last` is the highest input index inside the spot (its recency).
export function clusterBoxes(boxes, gap = 120) {
  const spots = [];
  boxes.forEach((b, index) => {
    let spot = { box: b, last: index };
    for (let i = spots.length - 1; i >= 0; i--) {
      if (intersects(grow(spots[i].box, gap / 2), grow(spot.box, gap / 2))) {
        spot = { box: union(spots[i].box, spot.box), last: Math.max(spots[i].last, spot.last) };
        spots.splice(i, 1);
      }
    }
    spots.push(spot);
  });
  return spots.sort((a, b) => b.last - a.last);      // most recent work first
}
