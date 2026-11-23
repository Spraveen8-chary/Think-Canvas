const test = require("node:test");
const assert = require("node:assert");

const load = (f) => import(`../../frontend/js/${f}`);
const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test("formulas: precedence, powers, functions, implicit multiplication", async () => {
  const { compile } = await load("mathexpr.js");
  assert.equal(compile("1 + 2 * 3")(0), 7);
  assert.equal(compile("2^3^2")(0), 512);                 // right associative
  assert.equal(compile("-x^2")(3), -9);                   // minus applies after the power
  assert.equal(compile("2x + 1")(4), 9);
  assert.equal(compile("3(x+1)")(2), 9);
  near(compile("sin(pi/2) + cos(0)")(0), 2);
  near(compile("sqrt(x)*e")(4), 2 * Math.E);
  assert.equal(compile("x**2")(5), 25);
  near(compile("sin(30*deg)")(0), 0.5);                  // degrees: 30*deg = 30 degrees
  assert.equal(compile("1/x")(0), Infinity);
});

test("formulas: anything unsafe or unknown is rejected (never evaluated)", async () => {
  const { compile } = await load("mathexpr.js");
  for (const bad of ["alert(1)", "x;1", "process", "sin x", "2 +", "(1", "x y z(", "1 + @", "constructor", "x".repeat(200)]) {
    assert.throws(() => compile(bad), undefined, bad);
  }
});

test("flowchart layout: levels, no overlap, arrows connect the boxes", async () => {
  const { layoutFlow } = await load("flow.js");
  const nodes = [["s", "Start", "oval"], ["c", "Valid?", "diamond"], ["y", "Log in", "box"], ["n", "Show error", "box"]];
  const edges = [["s", "c"], ["c", "y", "yes"], ["c", "n", "no"], ["n", "s"]];     // n -> s is a loop
  const lay = layoutFlow(nodes, edges, "down");
  const at = (id) => lay.nodes.find((n) => n.id === id);
  assert.ok(at("s").y < at("c").y && at("c").y < at("y").y);
  assert.equal(at("y").y, at("n").y);                      // same level
  for (const a of lay.nodes) for (const b of lay.nodes) {
    if (a !== b) assert.ok(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y, `${a.id} overlaps ${b.id}`);
  }
  assert.equal(lay.arrows.length, 4);
  assert.ok(lay.nodes.every((n) => n.x >= 0 && n.y >= 0 && n.x + n.w <= lay.w && n.y + n.h <= lay.h));
  const right = layoutFlow(nodes, edges, "right");
  assert.ok(right.nodes.find((n) => n.id === "s").x < right.nodes.find((n) => n.id === "c").x);
});

test("work spots: close items group together, newest spot first", async () => {
  const { clusterBoxes } = await load("geometry.js");
  const boxes = [
    { x: 0, y: 0, w: 50, h: 20 },          // 0  spot A
    { x: 3000, y: 3000, w: 50, h: 20 },    // 1  spot B
    { x: 60, y: 10, w: 50, h: 20 },        // 2  spot A again (newer than B)
    { x: -5000, y: 0, w: 10, h: 10 },      // 3  spot C (newest)
  ];
  const spots = clusterBoxes(boxes, 160);
  assert.equal(spots.length, 3);
  assert.equal(spots[0].box.x, -5000);                     // newest first
  assert.equal(spots[1].box.x, 0);                          // A (last touched at index 2)
  assert.equal(spots[1].box.w, 110);                        // A's two items merged
  assert.equal(spots[2].box.x, 3000);
});

test("animation: a ball follows a drawn path from start to end", async () => {
  const { sceneState, pointAlong } = await load("blocks.js");
  const arc = [[0, 100], [50, 0], [100, 100]];
  assert.deepEqual(pointAlong(arc, 0), [0, 100]);
  assert.deepEqual(pointAlong(arc, 1), [100, 100]);
  near(pointAlong(arc, 0.5)[0], 50);                       // halfway by length is the top of the symmetric arc
  const spec = { o: [{ id: "arc", type: "path", points: arc }, { id: "b", type: "circle", cx: 0, cy: 100, r: 5 }], m: [{ type: "follow", target: "b", along: "arc", ms: 1000 }] };
  const mid = sceneState(spec, 500).st.get("b");
  near(0 + mid.dx, 50); near(100 + mid.dy, 0);             // ball is at the top of the arc at half time
});

test("animation: planet orbits the sun and starts where it was drawn", async () => {
  const { sceneState } = await load("blocks.js");
  const spec = {
    o: [{ id: "sun", type: "circle", cx: 200, cy: 130, r: 20 }, { id: "p", type: "circle", cx: 300, cy: 130, r: 8 }],
    m: [{ type: "orbit", target: "p", center: "sun", rx: 100, ry: 100, ms: 4000 }, { type: "spin", target: "sun", ms: 1000 }],
  };
  const t0 = sceneState(spec, 0).st.get("p");
  near(t0.dx, 0, 1e-6); near(t0.dy, 0, 1e-6);              // starts at its drawn position
  const q = sceneState(spec, 1000).st.get("p");             // quarter turn: now below the sun
  near(300 + q.dx, 200, 1e-6); near(130 + q.dy, 230, 1e-6);
  near(sceneState(spec, 500).st.get("sun").rot, Math.PI);
});
