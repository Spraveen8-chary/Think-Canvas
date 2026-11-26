import test from "node:test";
import assert from "node:assert/strict";

import {
  applyTranscriptTurn,
  composeTranscriptText,
  createSilenceTimer,
  createTranscriptState,
  setCommittedText,
} from "../../frontend/js/transcript.js";

test("transcript merge: partials replace without appending, finals append once per turn_order", () => {
  let s = createTranscriptState();

  // Partial updates replace partialText
  s = applyTranscriptTurn(s, { turn_order: 0, transcript: "hello", end_of_turn: false });
  assert.equal(s.committedText, "");
  assert.equal(s.partialText, "hello");
  assert.equal(composeTranscriptText(s), "hello");

  s = applyTranscriptTurn(s, { turn_order: 0, transcript: "hello world", end_of_turn: false });
  assert.equal(s.committedText, "");
  assert.equal(s.partialText, "hello world");
  assert.equal(composeTranscriptText(s), "hello world");

  // Unformatted end_of_turn waits for formatted turn
  s = applyTranscriptTurn(s, { turn_order: 0, transcript: "hello world", end_of_turn: true, turn_is_formatted: false });
  assert.equal(s.committedText, "");
  assert.equal(s.partialText, "hello world");

  // Formatted final appends once and clears partial
  s = applyTranscriptTurn(s, { turn_order: 0, transcript: "Hello world.", end_of_turn: true, turn_is_formatted: true });
  assert.equal(s.committedText, "Hello world.");
  assert.equal(s.partialText, "");

  // Duplicate turn_order is ignored
  s = applyTranscriptTurn(s, { turn_order: 0, transcript: "Hello world.", end_of_turn: true, turn_is_formatted: true });
  assert.equal(s.committedText, "Hello world.");

  // Next turn appends with a single space
  s = applyTranscriptTurn(s, { turn_order: 1, transcript: "How are you?", end_of_turn: true, turn_is_formatted: true });
  assert.equal(composeTranscriptText(s), "Hello world. How are you?");
});

test("transcript merge: manual user edits are preserved across subsequent finals", () => {
  let s = createTranscriptState("Plot sin x");
  s = setCommittedText(s, "Plot sin(2*x)");
  s = applyTranscriptTurn(s, { turn_order: 2, transcript: "from 0 to 10.", end_of_turn: true, turn_is_formatted: true });
  assert.equal(s.committedText, "Plot sin(2*x) from 0 to 10.");
});

test("silence timer: fires once after 5s, resets on new speech, cancelled by Send/Disconnect", () => {
  let now = 0;
  let nextId = 1;
  const pending = new Map();
  const setTimer = (fn, ms) => { const id = nextId++; pending.set(id, { fn, at: now + ms }); return id; };
  const clearTimer = (id) => pending.delete(id);
  const advance = (ms) => {
    now += ms;
    for (const [id, t] of [...pending.entries()]) {
      if (t.at <= now) { pending.delete(id); t.fn(); }
    }
  };

  let fired = 0;
  const timer = createSilenceTimer({ timeoutMs: 5000, onFire: () => { fired++; }, setTimer, clearTimer });

  // No text -> does not arm
  timer.touch(false);
  assert.equal(timer.isArmed(), false);

  // Speech at t=0, another speech event at t=3000 resets the 5s window to t=8000
  timer.touch(true);
  assert.equal(timer.isArmed(), true);
  advance(3000);
  assert.equal(fired, 0);
  timer.touch(true);
  advance(3000);
  assert.equal(fired, 0);
  advance(2000);
  assert.equal(fired, 1);

  // Cannot double-fire while sending
  assert.equal(timer.tryBeginSend(), false);
  timer.finishSend();

  // Cancelled by manual Send or Disconnect
  timer.touch(true);
  assert.equal(timer.tryBeginSend(), true);
  assert.equal(timer.isArmed(), false);
  advance(6000);
  assert.equal(fired, 1);
  timer.finishSend();

  timer.touch(true);
  timer.cancel();
  assert.equal(timer.isArmed(), false);
  advance(6000);
  assert.equal(fired, 1);
});
