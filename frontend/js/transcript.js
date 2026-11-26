// Pure transcript-merging and auto-submit silence timer logic (no DOM).

export function createTranscriptState(committedText = "") {
  return {
    committedText: String(committedText || ""),
    partialText: "",
    seenTurnIds: new Set(),
  };
}

function joinWithSpace(base, addition) {
  const clean = String(addition || "").trim();
  if (!clean) return base;
  if (!base) return clean;
  return /\s$/.test(base) ? `${base}${clean}` : `${base} ${clean}`;
}

/**
 * Merge an incoming turn event into transcript state without duplicating finalized turns.
 * - Partials replace `partialText` (never appended).
 * - Finals (`end_of_turn` and `turn_is_formatted !== false`) append to `committedText` once per `turn_order`.
 */
export function applyTranscriptTurn(state, event) {
  const text = String(event?.transcript ?? "").trim();
  const turnId = event?.turn_order ?? event?.turnId ?? null;
  const isFinal = Boolean(event?.end_of_turn) && event?.turn_is_formatted !== false;

  if (isFinal) {
    if (turnId !== null && turnId !== undefined && state.seenTurnIds.has(turnId)) {
      return { ...state, partialText: "" };
    }
    const nextSeen = new Set(state.seenTurnIds);
    if (turnId !== null && turnId !== undefined) nextSeen.add(turnId);
    return {
      committedText: joinWithSpace(state.committedText, text),
      partialText: "",
      seenTurnIds: nextSeen,
    };
  }

  return {
    ...state,
    partialText: text,
  };
}

export function setCommittedText(state, editedText) {
  return {
    ...state,
    committedText: String(editedText ?? ""),
  };
}

export function composeTranscriptText(state) {
  return joinWithSpace(state.committedText, state.partialText);
}

/**
 * Auto-submit silence timer.
 * Fires `onFire()` once after `timeoutMs` of no `touch(true)` calls, and never double-fires.
 */
export function createSilenceTimer({
  timeoutMs = 5000,
  onFire,
  setTimer = (fn, ms) => setTimeout(fn, ms),
  clearTimer = (id) => clearTimeout(id),
  onStateChange = () => {},
} = {}) {
  let id = null;
  let enabled = true;
  let sending = false;
  let ms = Number(timeoutMs) || 5000;

  function cancel() {
    if (id !== null) {
      clearTimer(id);
      id = null;
      onStateChange({ armed: false, timeoutMs: ms });
    }
  }

  function trigger() {
    if (id === null || sending || !enabled) return;
    id = null;
    sending = true;
    onStateChange({ armed: false, timeoutMs: ms });
    onFire?.();
  }

  function touch(hasText) {
    cancel();
    if (!enabled || !hasText || sending) return;
    onStateChange({ armed: true, timeoutMs: ms });
    id = setTimer(trigger, ms);
  }

  function setEnabled(next) {
    enabled = Boolean(next);
    if (!enabled) cancel();
  }

  function setTimeoutMs(nextMs) {
    const parsed = Number(nextMs);
    if (Number.isFinite(parsed) && parsed >= 1000) ms = parsed;
  }

  function tryBeginSend() {
    if (sending) return false;
    sending = true;
    cancel();
    return true;
  }

  function finishSend() {
    sending = false;
  }

  return {
    touch,
    cancel,
    setEnabled,
    setTimeoutMs,
    tryBeginSend,
    finishSend,
    isArmed: () => id !== null,
  };
}
