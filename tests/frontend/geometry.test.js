const test = require("node:test");
const assert = require("node:assert");

const load = () => import("../../frontend/js/geometry.js");

test("bounds, union and intersection", async () => {
  const g = await load();
  const a = g.pointsBounds([[10, 20], [50, 30]]);
  assert.deepEqual(a, { x: 10, y: 20, w: 40, h: 10 });
  assert.deepEqual(g.union(a, { x: 0, y: 0, w: 5, h: 5 }), { x: 0, y: 0, w: 50, h: 30 });
  assert.equal(g.union(null, a), a);
  assert.ok(g.intersects(a, { x: 45, y: 25, w: 20, h: 20 }));
  assert.ok(!g.intersects(a, { x: 60, y: 0, w: 5, h: 5 }));
});

test("the answer goes to the right of the writing when there is room", async () => {
  const { placeAnswer } = await load();
  const spot = placeAnswer({ x: 100, y: 100, w: 200, h: 60 }, { w: 300, h: 80 }, { x: 0, y: 0, w: 1200, h: 800 });
  assert.deepEqual(spot, { x: 328, y: 100 });
});

test("the answer goes below the writing when the right side is off screen", async () => {
  const { placeAnswer } = await load();
  const spot = placeAnswer({ x: 700, y: 100, w: 200, h: 60 }, { w: 300, h: 80 }, { x: 0, y: 0, w: 1000, h: 800 });
  assert.deepEqual(spot, { x: 700, y: 188 });
});

test("answers do not overlap each other", async () => {
  const { placeAnswer, intersects } = await load();
  const taken = [{ x: 328, y: 100, w: 300, h: 80 }];
  const size = { w: 300, h: 80 };
  const spot = placeAnswer({ x: 100, y: 100, w: 200, h: 60 }, size, { x: 0, y: 0, w: 1200, h: 800 }, taken);
  assert.ok(!intersects(taken[0], { ...spot, ...size }));
});

test("text wraps to the given width", async () => {
  const { wrapText } = await load();
  const measure = (t) => t.length * 10;                 // 10px per character
  assert.deepEqual(wrapText("aaa bbb ccc", 70, measure), ["aaa bbb", "ccc"]);
  assert.deepEqual(wrapText("one\ntwo", 500, measure), ["one", "two"]);
  assert.ok(wrapText("x".repeat(25), 100, measure).every((l) => measure(l) <= 100));
});

test("eraser distance to a segment", async () => {
  const { distToSegment } = await load();
  assert.equal(distToSegment([5, 3], [0, 0], [10, 0]), 3);
  assert.equal(distToSegment([-4, 3], [0, 0], [10, 0]), 5);
});
