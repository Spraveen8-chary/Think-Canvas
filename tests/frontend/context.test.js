import test from "node:test";
import assert from "node:assert/strict";
import { splitContext, textOf, hasInk } from "../../frontend/js/context.js";

const stroke = (done) => ({ type: "stroke", points: [[0, 0], [1, 1]], ...(done ? { done: true } : {}) });
const text = (t, done) => ({ type: "text", text: t, ...(done ? { done: true } : {}) });

test("new writing is the question, answered writing is context", () => {
  const old = stroke(true), fresh = stroke(false), oldText = text("What is x?", true), newText = text("and for y?");
  const r = splitContext([old, fresh, oldText, newText]);
  assert.deepEqual(r.fresh, [fresh, newText]);
  assert.deepEqual(r.done, [old, oldText]);
  assert.equal(r.reread, false);
  assert.equal(textOf(r.fresh), "and for y?");
  assert.equal(textOf(r.done), "What is x?");
});

test("nothing new (Answer now on an answered spot) reads everything again", () => {
  const items = [stroke(true), text("2+2", true)];
  const r = splitContext(items);
  assert.equal(r.reread, true);
  assert.deepEqual(r.fresh, items);
  assert.deepEqual(r.done, []);
});

test("hasInk is true for strokes and images only", () => {
  assert.ok(hasInk([text("a"), stroke(false)]));
  assert.ok(!hasInk([text("a")]));
});
