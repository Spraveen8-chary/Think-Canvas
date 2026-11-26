// Live Session voice tutor (Gemini Live API) with gapless 24 kHz PCM playback,
// barge-in interruption, session resumption, and canvas tool calling.
import { api } from "./api.js";

function toBase64(bytes) {
  let bin = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}

function fromBase64(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function initLiveSession({ elements, onDrawBlock, onClearCanvas, getCanvasId }) {
  const { panel, toggleBtn, stateBadge, muteBtn, endBtn, transcriptEl } = elements;

  let ws = null;
  let micCtx = null;
  let workletNode = null;
  let mediaStream = null;
  let playCtx = null;
  let nextPlayTime = 0;
  let activeSources = new Set();
  let active = false;
  let muted = false;
  let userEnded = false;
  let sessionHandle = null;
  let modelName = "";
  let sessionTimer = null;
  let idleTimer = null;
  let idleTimeoutMs = 120000;

  let transcriptLog = []; // finalized turns [{role, text}]
  let drawnKinds = [];
  let cancelledCallIds = new Set();
  let userPartialEl = null;
  let modelPartialEl = null;
  let userBuffer = "";
  let modelBuffer = "";

  function setState(label, kind) {
    stateBadge.textContent = label;
    stateBadge.dataset.state = kind;
  }

  function resetIdleTimer() {
    clearTimeout(idleTimer);
    if (!active) return;
    idleTimer = setTimeout(() => endSession("Session ended due to inactivity."), idleTimeoutMs);
  }

  function stopPlayback() {
    for (const src of activeSources) {
      try { src.stop(); } catch {}
    }
    activeSources.clear();
    nextPlayTime = playCtx ? playCtx.currentTime : 0;
  }

  function playPcm24k(b64Data) {
    if (!playCtx) playCtx = new AudioContext({ sampleRate: 24000 });
    if (playCtx.state === "suspended") playCtx.resume();
    const bytes = fromBase64(b64Data);
    const int16 = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
    if (!int16.length) return;

    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 0x8000;

    const audioBuf = playCtx.createBuffer(1, float32.length, 24000);
    audioBuf.copyToChannel(float32, 0);

    const src = playCtx.createBufferSource();
    src.buffer = audioBuf;
    src.connect(playCtx.destination);
    const startAt = Math.max(playCtx.currentTime, nextPlayTime);
    src.start(startAt);
    nextPlayTime = startAt + audioBuf.duration;
    activeSources.add(src);
    src.onended = () => activeSources.delete(src);
  }

  function appendBubble(role, text, isPartial = false) {
    const clean = String(text || "").trim();
    if (!clean) return;
    if (role === "user") {
      if (!userPartialEl) {
        userPartialEl = document.createElement("div");
        userPartialEl.className = "live-msg user partial";
        userPartialEl.dir = "auto";
        transcriptEl.append(userPartialEl);
      }
      userPartialEl.textContent = clean;
      if (!isPartial) {
        userPartialEl.classList.remove("partial");
        transcriptLog.push({ role: "user", text: clean });
        userPartialEl = null;
      }
    } else {
      if (!modelPartialEl) {
        modelPartialEl = document.createElement("div");
        modelPartialEl.className = "live-msg model partial";
        modelPartialEl.dir = "auto";
        transcriptEl.append(modelPartialEl);
      }
      modelPartialEl.textContent = clean;
      if (!isPartial) {
        modelPartialEl.classList.remove("partial");
        transcriptLog.push({ role: "model", text: clean });
        modelPartialEl = null;
      }
    }
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  }

  function flushTurnTranscripts() {
    if (userBuffer.trim()) {
      appendBubble("user", userBuffer, false);
      userBuffer = "";
    }
    if (modelBuffer.trim()) {
      appendBubble("model", modelBuffer, false);
      modelBuffer = "";
    }
  }

  async function handleToolCalls(calls) {
    const responses = [];
    for (const call of calls) {
      if (cancelledCallIds.has(call.id)) {
        cancelledCallIds.delete(call.id);
        continue;
      }
      try {
        const res = await api.liveBlock(call.name, call.args || {});
        if (cancelledCallIds.has(call.id)) {
          cancelledCallIds.delete(call.id);
          continue;
        }
        if (res.action === "clear") {
          onClearCanvas();
        } else if (res.action === "draw" && res.block) {
          drawnKinds.push(res.block.t);
          onDrawBlock(res.block);
        }
        responses.push({ id: call.id, name: call.name, response: { output: { ok: true } } });
      } catch (err) {
        responses.push({ id: call.id, name: call.name, response: { output: { ok: false, error: err.message } } });
      }
    }
    if (ws && ws.readyState === WebSocket.OPEN && responses.length) {
      ws.send(JSON.stringify({ toolResponse: { functionResponses: responses } }));
    }
  }

  async function connectSocket({ token, model, ws_url }, resumeHandle = null) {
    const url = `${ws_url}?access_token=${encodeURIComponent(token)}`;
    ws = new WebSocket(url);

    ws.onopen = async () => {
      const setup = { model };
      if (resumeHandle) setup.sessionResumption = { handle: resumeHandle };
      ws.send(JSON.stringify({ setup }));
    };

    ws.onmessage = async (ev) => {
      let raw = ev.data;
      if (raw instanceof Blob) raw = await raw.text();
      let msg;
      try { msg = JSON.parse(raw); } catch { return; }

      resetIdleTimer();

      if (msg.setupComplete !== undefined) {
        setState("Live", "live");
        muteBtn.disabled = false;
        endBtn.disabled = false;
        return;
      }

      if (msg.sessionResumptionUpdate?.resumable && msg.sessionResumptionUpdate.newHandle) {
        sessionHandle = msg.sessionResumptionUpdate.newHandle;
      }

      if (msg.goAway) {
        reconnect();
        return;
      }

      const sc = msg.serverContent;
      if (sc) {
        if (sc.interrupted) {
          stopPlayback();
          flushTurnTranscripts();
        }
        if (sc.inputTranscription?.text) {
          userBuffer += sc.inputTranscription.text;
          appendBubble("user", userBuffer, true);
        }
        if (sc.outputTranscription?.text) {
          modelBuffer += sc.outputTranscription.text;
          appendBubble("model", modelBuffer, true);
        }
        if (sc.modelTurn?.parts) {
          for (const part of sc.modelTurn.parts) {
            if (part.inlineData?.mimeType?.startsWith("audio/pcm") && part.inlineData.data) {
              playPcm24k(part.inlineData.data);
            }
          }
        }
        if (sc.turnComplete) {
          flushTurnTranscripts();
        }
      }

      if (msg.toolCall?.functionCalls?.length) {
        await handleToolCalls(msg.toolCall.functionCalls);
      }
      if (msg.toolCallCancellation?.ids) {
        for (const id of msg.toolCallCancellation.ids) cancelledCallIds.add(id);
      }
    };

    ws.onclose = () => {
      if (userEnded || !active) return;
      reconnect();
    };

    ws.onerror = () => {
      if (!userEnded && active) setState("Error", "error");
    };
  }

  async function reconnect() {
    if (!active || userEnded) return;
    setState("Reconnecting", "reconnecting");
    try { ws?.close(); } catch {}
    ws = null;
    try {
      const creds = await api.liveToken();
      modelName = creds.model;
      await connectSocket(creds, sessionHandle);
    } catch (err) {
      endSession(err.message || "Could not reconnect.");
    }
  }

  async function startSession() {
    panel.hidden = false;
    toggleBtn.classList.add("on");
    if (active) return;

    userEnded = false;
    muted = false;
    muteBtn.textContent = "Mute";
    sessionHandle = null;
    transcriptLog = [];
    drawnKinds = [];
    userBuffer = "";
    modelBuffer = "";
    transcriptEl.innerHTML = "";
    setState("Connecting", "connecting");

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      const creds = await api.liveToken();
      modelName = creds.model;
      idleTimeoutMs = (creds.idle_timeout_s || 120) * 1000;

      micCtx = new AudioContext();
      await micCtx.audioWorklet.addModule("/js/pcm-worklet.js");
      const source = micCtx.createMediaStreamSource(mediaStream);
      workletNode = new AudioWorkletNode(micCtx, "pcm16-worklet");
      workletNode.port.onmessage = (ev) => {
        if (muted || !ws || ws.readyState !== WebSocket.OPEN) return;
        const b64 = toBase64(new Uint8Array(ev.data));
        ws.send(JSON.stringify({
          realtimeInput: { audio: { data: b64, mimeType: "audio/pcm;rate=16000" } },
        }));
      };
      source.connect(workletNode);

      active = true;
      clearTimeout(sessionTimer);
      sessionTimer = setTimeout(() => endSession("Maximum session length reached."), (creds.max_session_s || 1800) * 1000);
      resetIdleTimer();
      await connectSocket(creds, null);
    } catch (err) {
      cleanupAudio();
      active = false;
      setState("Error", "error");
      appendBubble("model", err.message || "Could not start Live Session.", false);
    }
  }

  function cleanupAudio() {
    stopPlayback();
    if (workletNode) { try { workletNode.disconnect(); } catch {} workletNode = null; }
    if (micCtx) { try { micCtx.close(); } catch {} micCtx = null; }
    if (playCtx) { try { playCtx.close(); } catch {} playCtx = null; }
    if (mediaStream) { for (const t of mediaStream.getTracks()) t.stop(); mediaStream = null; }
  }

  async function endSession(note = "") {
    userEnded = true;
    active = false;
    clearTimeout(sessionTimer);
    clearTimeout(idleTimer);
    flushTurnTranscripts();

    try { ws?.close(); } catch {}
    ws = null;
    cleanupAudio();

    muteBtn.disabled = true;
    endBtn.disabled = true;
    toggleBtn.classList.remove("on");
    setState("Ended", "ended");
    if (note) appendBubble("model", note, false);

    if (transcriptLog.length || drawnKinds.length) {
      try {
        await api.liveHistory(getCanvasId(), transcriptLog, drawnKinds);
      } catch {}
    }
  }

  toggleBtn.onclick = () => {
    if (active) {
      panel.hidden = !panel.hidden;
    } else {
      startSession();
    }
  };
  muteBtn.onclick = () => {
    muted = !muted;
    muteBtn.textContent = muted ? "Unmute" : "Mute";
  };
  endBtn.onclick = () => endSession();

  window.addEventListener("pagehide", () => { if (active) endSession(); });
  window.addEventListener("beforeunload", () => { if (active) endSession(); });

  return { startSession, endSession };
}
