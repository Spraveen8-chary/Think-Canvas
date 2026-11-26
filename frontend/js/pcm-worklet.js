// AudioWorkletProcessor: downsamples microphone Float32 audio to 16 kHz mono PCM16
// and posts ~50 ms frames (800 samples = 1600 bytes) to the main thread.
const TARGET_RATE = 16000;
const FRAME_SAMPLES = 800; // 50 ms at 16 kHz

class Pcm16WorkletProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Int16Array(FRAME_SAMPLES);
    this._filled = 0;
    this._phase = 0;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input || !input.length) return true;

    const ratio = sampleRate / TARGET_RATE;
    let pos = this._phase;
    while (pos < input.length) {
      const idx = Math.floor(pos);
      const s = Math.max(-1, Math.min(1, input[idx]));
      this._buffer[this._filled++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this._filled === FRAME_SAMPLES) {
        const out = this._buffer.slice();
        this.port.postMessage(out.buffer, [out.buffer]);
        this._filled = 0;
      }
      pos += ratio;
    }
    this._phase = pos - input.length;
    return true;
  }
}

registerProcessor("pcm16-worklet", Pcm16WorkletProcessor);
