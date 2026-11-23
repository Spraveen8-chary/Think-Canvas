// The drawing surface: grid, pen, eraser, typed text, images, pan, and the AI's answers.
// Everything on the canvas is an "item" in canvas (world) coordinates; `view` is the scroll offset:
//   stroke  { type, points }            pen stroke
//   text    { type, x, y, w, text }     text the user typed
//   image   { type, assetId, x, y, w, h }   image the user imported
//   answer  { type, x, y, w, text }     AI text
//   plot | chart | flow | draw | anim   { type, x, y, w, h, spec }   AI visuals (see blocks.js)
import { pointsBounds, grow, intersects, contains, union, distToSegment, placeAnswer, wrapText, clusterBoxes } from "./geometry.js";
import { makeBlockItem, paintBlock, isVisualType } from "./blocks.js";

const COLORS = { ink: "#1f2430", answer: "#2447d6", answerBg: "rgba(36,71,214,.07)", minor: "#e9ecf3", major: "#d6dbe8", spot: "#4a6cf7" };
const GRID = 32;
const PEN_WIDTH = 3;
const ERASER_RADIUS = 16;
const ANSWER_FONT = '21px "Segoe Print", "Bradley Hand", "Comic Sans MS", cursive';
const TYPED_FONT = '20px system-ui, "Segoe UI", sans-serif';
const ANSWER_LINE = 29, ANSWER_PAD = 12, ANSWER_WIDTH = 340;
const TYPED_LINE = 26, TYPED_WIDTH = 420;
const USER_TYPES = ["stroke", "text", "image"];          // what the user put on the canvas (the AI reads these)
const mod = (a, n) => ((a % n) + n) % n;

export class Board {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.items = [];
    this.view = { x: 0, y: 0 };
    this.tool = "pen";                 // pen | text | eraser | hand
    this.grid = "lines";               // lines | dots | none
    this.spot = null;                  // dashed box: the writing the AI is about to read
    this.spaceDown = false;
    this.locked = false;               // true while a canvas is loading: ignore the pen so nothing is lost
    this.spotIndex = -1;               // which work spot "Find my work" showed last

    this.onStrokeStart = () => {};
    this.onUserInput = () => {};       // (box) the user added writing / text / an image
    this.onTextClick = () => {};       // (world, screen) the user clicked with the text tool
    this.onChange = () => {};          // saved items changed
    this.onView = () => {};            // the visible area moved

    this.layouts = new Map();
    this.bounds = new WeakMap();
    this.images = new Map();
    this.drag = null;
    this.raf = null;
    new ResizeObserver(() => this.resize()).observe(canvas);
    this.bindPointer();
  }

  // ---- size and coordinates ------------------------------------------------------------
  get cssSize() { return { w: this.canvas.clientWidth, h: this.canvas.clientHeight }; }

  resize() {
    const dpr = window.devicePixelRatio || 1, { w, h } = this.cssSize;
    this.canvas.width = Math.max(1, Math.round(w * dpr));
    this.canvas.height = Math.max(1, Math.round(h * dpr));
    this.render();
    this.onView();
  }

  toWorld(e) {
    const r = this.canvas.getBoundingClientRect();
    return [e.clientX - r.left + this.view.x, e.clientY - r.top + this.view.y];
  }

  viewBox() { return { x: this.view.x, y: this.view.y, ...this.cssSize }; }

  setTool(tool) {
    this.tool = tool;
    this.canvas.style.cursor = { pen: "crosshair", text: "text", eraser: "cell", hand: "grab" }[tool];
  }

  // ---- input ---------------------------------------------------------------------------
  bindPointer() {
    const c = this.canvas;
    c.addEventListener("pointerdown", (e) => {
      if (this.locked) return;
      const p = this.toWorld(e);
      if (this.tool === "text" && !this.spaceDown && e.button === 0) {
        e.preventDefault();                                 // keep focus for the text box that opens
        this.onTextClick({ x: p[0], y: p[1] }, { x: e.clientX, y: e.clientY });
        return;
      }
      c.setPointerCapture(e.pointerId);
      if (this.tool === "hand" || this.spaceDown || e.button === 1) {
        this.drag = { mode: "pan", x: e.clientX, y: e.clientY };
      } else if (this.tool === "eraser") {
        this.drag = { mode: "erase", last: p, erased: false };
        this.eraseAt(p, p);
      } else {
        const stroke = { type: "stroke", points: [p] };
        this.items.push(stroke);
        this.drag = { mode: "draw", stroke };
        this.onStrokeStart();
        this.render();
      }
    });

    c.addEventListener("pointermove", (e) => {
      const d = this.drag;
      if (!d) return;
      if (d.mode === "pan") {
        this.view.x -= e.clientX - d.x;
        this.view.y -= e.clientY - d.y;
        d.x = e.clientX; d.y = e.clientY;
        this.render(); this.onView();
      } else if (d.mode === "erase") {
        const p = this.toWorld(e);
        this.eraseAt(d.last, p);
        d.last = p;
      } else {
        const p = this.toWorld(e), last = d.stroke.points.at(-1);
        if (Math.hypot(p[0] - last[0], p[1] - last[1]) >= 1.5) {
          d.stroke.points.push(p);
          this.render();
        }
      }
    });

    const end = () => {
      const d = this.drag;
      this.drag = null;
      if (!d) return;
      if (d.mode === "draw") {
        const s = d.stroke;
        if (s.points.length === 1) s.points.push([s.points[0][0] + 0.1, s.points[0][1]]);
        s.points = s.points.map(([x, y]) => [Math.round(x * 10) / 10, Math.round(y * 10) / 10]);
        this.onUserInput(this.boxOf(s));
        this.onChange();
        this.onView();
      } else if (d.mode === "erase" && d.erased) {
        this.onChange();
        this.onView();
      }
    };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);

    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.view.x += e.deltaX;
      this.view.y += e.deltaY;
      this.render(); this.onView();
    }, { passive: false });
  }

  // Object eraser: removes whatever the eraser touches.
  eraseAt(a, b) {
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const hits = (it) => {
      if (it.type !== "stroke") { const box = this.boxOf(it); return contains(box, b) || contains(box, mid); }
      return it.points.some((q, i) => i && (distToSegment(b, it.points[i - 1], q) < ERASER_RADIUS || distToSegment(mid, it.points[i - 1], q) < ERASER_RADIUS));
    };
    const before = this.items.length;
    this.items = this.items.filter((it) => !hits(it));
    if (this.items.length !== before) {
      if (this.drag) this.drag.erased = true;
      this.render();
    }
  }

  // ---- items and their boxes -------------------------------------------------------------
  setItems(items) {
    this.items = Array.isArray(items) ? items : [];
    this.view = { x: 0, y: 0 };
    this.spot = null;
    this.spotIndex = -1;
    this.layouts.clear();
    if (this.items.length) this.goToSpot(0);              // open where the latest work is
    else this.render();
    this.onView();
  }
  undo() { if (this.items.pop()) { this.render(); this.onChange(); this.onView(); } }
  clear() { this.items = []; this.render(); this.onChange(); this.onView(); }

  textLayout(item, font, width, line, pad) {
    const key = `${font}|${item.w || width}|${item.text}`;
    if (!this.layouts.has(key)) {
      this.ctx.font = font;
      const lines = wrapText(item.text, (item.w || width) - 2 * pad, (t) => this.ctx.measureText(t).width);
      this.layouts.set(key, { lines, h: lines.length * line + 2 * pad });
    }
    return this.layouts.get(key);
  }
  answerLayout(item) { return this.textLayout(item, ANSWER_FONT, ANSWER_WIDTH, ANSWER_LINE, ANSWER_PAD); }
  typedLayout(item) { return this.textLayout(item, TYPED_FONT, TYPED_WIDTH, TYPED_LINE, 4); }

  boxOf(item) {
    if (item.type === "stroke") {
      const hit = this.bounds.get(item);
      if (hit && hit.n === item.points.length) return hit.box;
      const box = pointsBounds(item.points);
      this.bounds.set(item, { n: item.points.length, box });
      return box;
    }
    if (item.type === "answer") return { x: item.x, y: item.y, w: item.w, h: this.answerLayout(item).h };
    if (item.type === "text") return { x: item.x, y: item.y, w: item.w || TYPED_WIDTH, h: this.typedLayout(item).h };
    return { x: item.x, y: item.y, w: item.w, h: item.h };
  }

  get hasAnimation() { return this.items.some((i) => i.type === "anim"); }

  // The items the AI should read for a spot: pen strokes, typed text and images touching `box`.
  itemsNear(box) {
    const area = grow(box, 24);
    return this.items.filter((i) => USER_TYPES.includes(i.type) && intersects(this.boxOf(i), area));
  }
  unionBox(items, seed) { return items.reduce((b, i) => union(b, this.boxOf(i)), seed); }

  inkBounds() {
    return this.items.filter((i) => USER_TYPES.includes(i.type)).reduce((b, i) => union(b, this.boxOf(i)), null);
  }

  // ---- adding things ---------------------------------------------------------------------
  addText(text, x, y) {
    const item = { type: "text", x: Math.round(x), y: Math.round(y), w: TYPED_WIDTH, text };
    this.items.push(item);
    this.render();
    this.onChange();
    this.onUserInput(this.boxOf(item));
    return item;
  }

  addImage(assetId, x, y, w, h) {
    const item = { type: "image", assetId, x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
    this.items.push(item);
    this.revealBox(item);
    this.render();
    this.onChange();
    this.onUserInput(this.boxOf(item));
    this.onView();
    return item;
  }

  // Card width that fits the text: a one-word answer gets a small card, long text wraps at ANSWER_WIDTH.
  answerWidth(text) {
    this.ctx.font = ANSWER_FONT;
    const longest = Math.max(...String(text).split("\n").map((l) => this.ctx.measureText(l).width));
    return Math.round(Math.min(ANSWER_WIDTH, Math.max(90, longest + 2 * ANSWER_PAD + 10)));
  }

  // Writes the AI's blocks on the canvas next to the user's input at `writingBox`.
  addBlocks(blocks, writingBox) {
    let anchor = writingBox, last = null;
    for (const block of blocks) {
      const item = block.t === "text" ? { type: "answer", x: 0, y: 0, w: this.answerWidth(block.text), text: block.text } : makeBlockItem(block);
      if (!item) continue;
      const size = this.boxOf(item);
      const taken = this.items.filter((i) => !USER_TYPES.includes(i.type)).map((i) => this.boxOf(i));
      const pos = placeAnswer(anchor, { w: size.w, h: size.h }, this.viewBox(), taken);
      item.x = Math.round(pos.x);
      item.y = Math.round(pos.y);
      this.items.push(item);
      last = this.boxOf(item);
      anchor = { x: writingBox.x, y: Math.max(writingBox.y + writingBox.h, last.y + last.h), w: writingBox.w, h: 0 };   // next block goes below
    }
    if (last) this.revealBox(last);
    this.render();
    this.onChange();
    this.onView();
    return Boolean(last);
  }

  // Scrolls just enough so `box` is visible.
  revealBox(box) {
    const v = this.viewBox(), m = 24;
    if (box.x < v.x) this.view.x = box.x - m;
    else if (box.x + box.w > v.x + v.w) this.view.x = box.x + box.w - v.w + m;
    if (box.y < v.y) this.view.y = box.y - m;
    else if (box.y + box.h > v.y + v.h) this.view.y = box.y + box.h - v.h + m;
  }

  // ---- finding your work -------------------------------------------------------------------
  // Spots of work (clusters of items), most recent first.
  spots() { return clusterBoxes(this.items.map((i) => this.boxOf(i)), 160).map((s) => s.box); }

  contentVisible() {
    const v = this.viewBox();
    return !this.items.length || this.items.some((i) => intersects(this.boxOf(i), v));
  }

  // Centres the view on the n-th most recent spot. Returns {index, total} or null when empty.
  goToSpot(n) {
    const spots = this.spots();
    if (!spots.length) return null;
    const index = mod(n, spots.length), b = spots[index], { w, h } = this.cssSize;
    this.view.x = Math.round(b.w > w - 80 ? b.x - 40 : b.x + b.w / 2 - w / 2);
    this.view.y = Math.round(b.h > h - 80 ? b.y - 40 : b.y + b.h / 2 - h / 2);
    this.spotIndex = index;
    this.render();
    this.onView();
    return { index, total: spots.length };
  }
  nextSpot() { return this.goToSpot(this.spotIndex + 1); }

  // ---- picture for the AI --------------------------------------------------------------------
  // Small PNG of the user's writing/images in `box` (white background, no grid, no answers).
  // Long side <= maxSide pixels: image tokens grow with picture size, so smaller is cheaper.
  snapshot(items, box, maxSide = 768) {
    const b = grow(box, 20);
    let scale = Math.min(1, maxSide / Math.max(b.w, b.h));
    if (Math.max(b.w, b.h) < 240) scale = Math.min(2, 240 / Math.max(b.w, b.h));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.ceil(b.w * scale));
    c.height = Math.max(1, Math.ceil(b.h * scale));
    const g = c.getContext("2d");
    g.fillStyle = "#fff";
    g.fillRect(0, 0, c.width, c.height);
    g.scale(scale, scale);
    g.translate(-b.x, -b.y);
    for (const it of items) {
      if (it.type === "stroke") this.paintStroke(g, it, Math.max(3, 2.4 / scale));
      else if (it.type === "image") this.paintImage(g, it);
    }
    return c.toDataURL("image/png");
  }

  // ---- drawing ---------------------------------------------------------------------------------
  paintStroke(g, stroke, width = PEN_WIDTH) {
    const p = stroke.points;
    g.strokeStyle = COLORS.ink;
    g.lineWidth = width;
    g.lineCap = g.lineJoin = "round";
    g.beginPath();
    g.moveTo(p[0][0], p[0][1]);
    for (let i = 1; i < p.length - 1; i++) {
      g.quadraticCurveTo(p[i][0], p[i][1], (p[i][0] + p[i + 1][0]) / 2, (p[i][1] + p[i + 1][1]) / 2);
    }
    g.lineTo(p.at(-1)[0], p.at(-1)[1]);
    g.stroke();
  }

  paintImage(g, item) {
    let img = this.images.get(item.assetId);
    if (!img) {
      img = new Image();
      img.onload = () => this.render();
      img.src = `/api/assets/${item.assetId}`;
      this.images.set(item.assetId, img);
    }
    if (img.complete && img.naturalWidth) g.drawImage(img, item.x, item.y, item.w, item.h);
    else { g.fillStyle = "#eef0f6"; g.fillRect(item.x, item.y, item.w, item.h); }
  }

  paintText(g, item, font, color, line, pad, dx = 0) {
    const { lines } = this.textLayout(item, font, item.w, line, pad);
    g.fillStyle = color;
    g.font = font;
    g.textBaseline = "middle";
    g.textAlign = "left";
    lines.forEach((l, i) => g.fillText(l, item.x + pad + dx, item.y + pad + line * (i + 0.5)));
  }

  paintAnswer(g, item) {
    const { h } = this.answerLayout(item);
    g.fillStyle = COLORS.answerBg;
    g.beginPath();
    g.roundRect ? g.roundRect(item.x, item.y, item.w, h, 10) : g.rect(item.x, item.y, item.w, h);
    g.fill();
    g.fillStyle = COLORS.answer;
    g.fillRect(item.x, item.y + 6, 3, h - 12);
    this.paintText(g, item, ANSWER_FONT, COLORS.answer, ANSWER_LINE, ANSWER_PAD, 4);
  }

  paintGrid(g, w, h) {
    if (this.grid === "none") return;
    const ox = mod(-this.view.x, GRID), oy = mod(-this.view.y, GRID);
    const isMajor = (screen, offset) => mod(Math.round((screen + offset) / GRID), 5) === 0;
    if (this.grid === "dots") {
      g.fillStyle = COLORS.major;
      for (let x = ox; x < w; x += GRID) {
        for (let y = oy; y < h; y += GRID) {
          const big = isMajor(x, this.view.x) && isMajor(y, this.view.y);
          g.fillRect(Math.round(x) - (big ? 1.5 : 1), Math.round(y) - (big ? 1.5 : 1), big ? 3 : 2, big ? 3 : 2);
        }
      }
      return;
    }
    g.lineWidth = 1;
    for (let x = ox; x < w; x += GRID) {
      g.strokeStyle = isMajor(x, this.view.x) ? COLORS.major : COLORS.minor;
      g.beginPath(); g.moveTo(Math.round(x) + 0.5, 0); g.lineTo(Math.round(x) + 0.5, h); g.stroke();
    }
    for (let y = oy; y < h; y += GRID) {
      g.strokeStyle = isMajor(y, this.view.y) ? COLORS.major : COLORS.minor;
      g.beginPath(); g.moveTo(0, Math.round(y) + 0.5); g.lineTo(w, Math.round(y) + 0.5); g.stroke();
    }
  }

  render() {
    const g = this.ctx, dpr = window.devicePixelRatio || 1, { w, h } = this.cssSize, now = performance.now();
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = "#fff";
    g.fillRect(0, 0, w, h);
    this.paintGrid(g, w, h);
    g.translate(-this.view.x, -this.view.y);
    for (const it of this.items) {
      if (it.type === "stroke") this.paintStroke(g, it);
      else if (it.type === "text") this.paintText(g, it, TYPED_FONT, COLORS.ink, TYPED_LINE, 4);
      else if (it.type === "image") this.paintImage(g, it);
      else if (it.type === "answer") this.paintAnswer(g, it);
      else if (isVisualType(it.type)) paintBlock(g, it, now);
    }
    if (this.spot) {                                  // the writing the AI is about to read
      const s = grow(this.spot, 10);
      g.setLineDash([7, 5]);
      g.lineWidth = 1.5;
      g.strokeStyle = COLORS.spot;
      g.beginPath();
      g.roundRect ? g.roundRect(s.x, s.y, s.w, s.h, 8) : g.rect(s.x, s.y, s.w, s.h);
      g.stroke();
      g.setLineDash([]);
    }
    this.keepAnimating();
  }

  // Animations redraw ~30 times a second, only while one is on the canvas and visible.
  keepAnimating() {
    if (this.raf || !this.hasAnimation) return;
    const v = this.viewBox();
    if (!this.items.some((i) => i.type === "anim" && intersects(this.boxOf(i), v))) return;
    this.raf = setTimeout(() => { this.raf = null; this.render(); }, 33);
  }
}
