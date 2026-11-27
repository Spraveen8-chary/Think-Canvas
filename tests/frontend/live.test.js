import test from "node:test";
import assert from "node:assert/strict";
import { inLanguage } from "../../frontend/js/live.js";

test("English speech: Latin letters, digits and punctuation are fine", () => {
  assert.ok(inLanguage("what is the derivative of x squared?", "en"));
  assert.ok(inLanguage("2 + 2 = 4, café", "en"));
});

test("English speech: transcripts in other scripts are rejected (noise hallucinations)", () => {
  assert.ok(!inLanguage("नमस्ते आप कैसे हैं", "en"));
  assert.ok(!inLanguage("你好世界", "en"));
  assert.ok(!inLanguage("hello हैलो", "en"));
});

test("Hindi / Telugu / Tamil speech accept their own script and Latin only", () => {
  assert.ok(inLanguage("नमस्ते sir, derivative क्या है", "hi"));
  assert.ok(!inLanguage("హలో", "hi"));
  assert.ok(inLanguage("హలో sir", "te"));
  assert.ok(!inLanguage("नमस्ते", "te"));
  assert.ok(inLanguage("வணக்கம் sir", "ta"));
});
