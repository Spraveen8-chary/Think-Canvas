// Live speech-to-text (AssemblyAI Universal-Streaming v3) + pre-recorded fallback + auto-send.
import { api } from "./api.js";
import {
  applyTranscriptTurn,
  composeTranscriptText,
  createSilenceTimer,
  createTranscriptState,
  setCommittedText,
} from "./transcript.js";

// Boosts words speech models often mishear in study questions.
const KEYTERMS = ["sine", "cosine", "tangent", "theta", "x squared", "flowchart", "binary search", "algorithm", "array", "integral", "derivative", "quadratic"];
const STREAMING_LANGS = new Set(["auto", "en", "es", "fr", "de", "it", "pt"]);

export function initStt({ elements, onSubmitText, defaultSilenceMs = 5000, store }) {
  const {
    panel, toggleBtn, closeBtn, connectBtn, sendBtn, clearBtn,
    langSelect, autoCheck, silenceSelect, stateBadge, modeNote,
    countdownEl, textarea, partialEl,
  } = elements;

  let state = createTranscriptState();
  let ws = null;
  let audioCtx = null;
  let workletNode = null;
  let mediaStream = null;
  let mediaRecorder = null;
  let recordedChunks = [];
  let connected = false;
  let userClosing = false;
  let retriedToken = false;
  let countdownInterval = null;
  let countdownEndsAt = 0;

  // Restore saved preferences
  const savedAuto = store.get("tc.stt.auto", "1") === "1";
  const savedSilence = Number(store.get("tc.stt.silenceMs", 0)) || defaultSilenceMs || 5000;
  autoCheck.checked = savedAuto;
  silenceSelect.value = String(savedSilence);
  if (!silenceSelect.value) {
    silenceSelect.add(new Option(`${(savedSilence / 1000).toFixed(0)} s`, String(savedSilence)));
    silenceSelect.value = String(savedSilence);
  }

  function setState(label, kind) {
    stateBadge.textContent = label;
    stateBadge.dataset.state = kind;
  }

  function updateCountdown(armed, timeoutMs) {
    clearInterval(countdownInterval);
    countdownInterval = null;
    if (!armed) {
      countdownEl.hidden = true;
      countdownEl.textContent = "";
      return;
    }
    countdownEndsAt = Date.now() + timeoutMs;
    countdownEl.hidden = false;
    const tick = () => {
      const left = Math.max(0, Math.ceil((countdownEndsAt - Date.now()) / 1000));
      countdownEl.textContent = `Sending in ${left}s…`;
      if (left <= 0) clearInterval(countdownInterval);
    };
    tick();
    countdownInterval = setInterval(tick, 250);
  }

  const silenceTimer = createSilenceTimer({
    timeoutMs: savedSilence,
    onFire: () => submitCurrent(),
    onStateChange: ({ armed, timeoutMs }) => updateCountdown(armed, timeoutMs),
  });
  silenceTimer.setEnabled(savedAuto);

  function syncUi() {
    textarea.value = state.committedText;
    partialEl.textContent = state.partialText;
  }

  function isStreamingMode() {
    return STREAMING_LANGS.has(langSelect.value);
  }

  function updateModeLabel() {
    modeNote.textContent = isStreamingMode()
      ? "Mode: Live streaming (AssemblyAI v3)"
      : "Mode: Pre-recorded fallback (record, then Disconnect to transcribe)";
  }
  updateModeLabel();

  async function submitCurrent() {
    const text = composeTranscriptText(state).trim();
    if (!text) {
      silenceTimer.finishSend();
      return;
    }
    if (!silenceTimer.tryBeginSend() && !text) return;
    // Clear transcript buffer immediately before async submit so new speech starts fresh
    state = createTranscriptState();
    syncUi();
    try {
      await onSubmitText(text);
    } finally {
      silenceTimer.finishSend();
    }
  }

  function releaseAudio() {
    if (workletNode) {
      try { workletNode.disconnect(); } catch {}
      workletNode = null;
    }
    if (audioCtx) {
      try { audioCtx.close(); } catch {}
      audioCtx = null;
    }
    if (mediaStream) {
      for (const t of mediaStream.getTracks()) t.stop();
      mediaStream = null;
    }
  }

  function disconnect({ keepState = false } = {}) {
    userClosing = true;
    silenceTimer.cancel();

    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
      return; // onstop will upload and releaseAudio
    }

    if (ws) {
      try {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "Terminate" }));
        }
        ws.close();
      } catch {}
      ws = null;
    }
    releaseAudio();
    connected = false;
    connectBtn.textContent = "Connect";
    if (!keepState) setState("Idle", "idle");
  }

  async function startStreaming() {
    setState("Connecting", "connecting");
    userClosing = false;
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch (e) {
      setState("Error", "error");
      partialEl.textContent = e.name === "NotAllowedError" ? "Microphone permission denied." : "Could not access microphone.";
      return;
    }

    // Handle device unplugged
    for (const track of mediaStream.getTracks()) {
      track.onended = () => {
        if (connected) {
          disconnect({ keepState: true });
          setState("Error", "error");
          partialEl.textContent = "Microphone disconnected.";
        }
      };
    }

    try {
      const { token, ws_url } = await api.sttToken();
      const model = langSelect.value === "en" ? "universal-streaming-english" : "universal-streaming-multilingual";
      const url = `${ws_url}?sample_rate=16000&format_turns=true&keyterms_prompt=${encodeURIComponent(JSON.stringify(KEYTERMS))}&speech_model=${encodeURIComponent(model)}&token=${encodeURIComponent(token)}`;

      ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";

      ws.onopen = async () => {
        try {
          audioCtx = new AudioContext();
          await audioCtx.audioWorklet.addModule("/js/pcm-worklet.js");
          const source = audioCtx.createMediaStreamSource(mediaStream);
          workletNode = new AudioWorkletNode(audioCtx, "pcm16-worklet");
          workletNode.port.onmessage = (ev) => {
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send(ev.data);
            }
          };
          source.connect(workletNode);
          connected = true;
          retriedToken = false;
          connectBtn.textContent = "Disconnect";
          setState("Listening", "listening");
        } catch (err) {
          disconnect({ keepState: true });
          setState("Error", "error");
          partialEl.textContent = err.message || "Audio worklet failed.";
        }
      };

      ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.type === "Turn") {
          state = applyTranscriptTurn(state, msg);
          syncUi();
          const hasText = Boolean(composeTranscriptText(state).trim());
          if (hasText) silenceTimer.touch(true);
        } else if (msg.type === "Error" || msg.error) {
          setState("Error", "error");
          partialEl.textContent = msg.error || "Streaming error.";
        }
      };

      ws.onclose = async (ev) => {
        if (userClosing) return;
        const tokenExpired = ev.code === 4001 || ev.code === 1008;
        if (tokenExpired && !retriedToken) {
          retriedToken = true;
          releaseAudio();
          ws = null;
          await startStreaming();
          return;
        }
        disconnect({ keepState: true });
        setState("Error", "error");
        partialEl.textContent = "Speech connection closed.";
      };

      ws.onerror = () => {
        if (!userClosing) setState("Error", "error");
      };
    } catch (e) {
      releaseAudio();
      setState("Error", "error");
      partialEl.textContent = e.message || "Could not connect to speech service.";
    }
  }

  async function startFallbackRecording() {
    setState("Connecting", "connecting");
    userClosing = false;
    recordedChunks = [];
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
      mediaRecorder = new MediaRecorder(mediaStream, { mimeType });
      mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) recordedChunks.push(e.data); };
      mediaRecorder.onstop = async () => {
        const blob = new Blob(recordedChunks, { type: mimeType });
        recordedChunks = [];
        mediaRecorder = null;
        releaseAudio();
        connected = false;
        connectBtn.textContent = "Connect";
        if (blob.size === 0) {
          setState("Idle", "idle");
          return;
        }
        setState("Transcribing…", "transcribing");
        try {
          const lang = langSelect.value === "fallback-auto" ? "auto" : langSelect.value;
          const res = await api.sttTranscribe(blob, lang);
          if (res.text) {
            state = applyTranscriptTurn(state, { transcript: res.text, end_of_turn: true, turn_is_formatted: true });
            syncUi();
            silenceTimer.touch(true);
          }
          setState("Idle", "idle");
        } catch (err) {
          setState("Error", "error");
          partialEl.textContent = err.message || "Transcription failed.";
        }
      };
      mediaRecorder.start(250);
      connected = true;
      connectBtn.textContent = "Stop & Transcribe";
      setState("Listening", "listening");
    } catch (e) {
      releaseAudio();
      setState("Error", "error");
      partialEl.textContent = e.name === "NotAllowedError" ? "Microphone permission denied." : "Could not access microphone.";
    }
  }

  // ---- UI wiring -----------------------------------------------------------------------
  toggleBtn.onclick = () => {
    panel.hidden = !panel.hidden;
    toggleBtn.classList.toggle("on", !panel.hidden);
  };
  closeBtn.onclick = () => {
    disconnect();
    panel.hidden = true;
    toggleBtn.classList.remove("on");
  };
  connectBtn.onclick = () => {
    if (connected) disconnect();
    else if (isStreamingMode()) startStreaming();
    else startFallbackRecording();
  };
  langSelect.onchange = () => {
    updateModeLabel();
    if (connected) disconnect();
  };
  autoCheck.onchange = () => {
    const on = autoCheck.checked;
    store.set("tc.stt.auto", on ? "1" : "0");
    silenceTimer.setEnabled(on);
    if (on && composeTranscriptText(state).trim()) silenceTimer.touch(true);
  };
  silenceSelect.onchange = () => {
    const ms = Number(silenceSelect.value) || 5000;
    store.set("tc.stt.silenceMs", String(ms));
    silenceTimer.setTimeoutMs(ms);
    if (silenceTimer.isArmed()) silenceTimer.touch(true);
  };
  textarea.oninput = () => {
    state = setCommittedText(state, textarea.value);
    const hasText = Boolean(composeTranscriptText(state).trim());
    if (hasText) silenceTimer.touch(true);
    else silenceTimer.cancel();
  };
  sendBtn.onclick = () => {
    if (silenceTimer.tryBeginSend()) submitCurrent();
  };
  clearBtn.onclick = () => {
    silenceTimer.cancel();
    state = createTranscriptState();
    syncUi();
  };

  window.addEventListener("pagehide", () => disconnect());
  window.addEventListener("beforeunload", () => disconnect());

  return { disconnect };
}
