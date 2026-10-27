/** Push-to-talk mic capture for voice chat.
 *
 *  Captures mono PCM straight from the microphone and encodes it as a 16-bit
 *  WAV for `POST /voice/transcribe`. PCM (not MediaRecorder) means the upload
 *  format is always WAV — no container/codec guessing between browsers — and
 *  the same stream drives the silence endpointer: once ~0.5 s of speech has
 *  been heard, 1.5 s of quiet ends the turn (a short adaptation of Codename
 *  Jo's turn policy — see docs/codenamejo-integration.md §3.2).
 */

export const SILENCE_END_MS = 1500;
export const MIN_SPEECH_MS = 500;
export const MAX_RECORD_MS = 30_000;
const SPEECH_RMS = 0.02; // below this a frame counts as silence
const FRAME = 4096;

export type StopReason = "silence" | "max" | "manual";

export type RecorderCallbacks = {
  onEnd?: (blob: Blob, reason: StopReason) => void;
};

export class MicRecorder {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private chunks: Float32Array[] = [];
  private startedAt = 0;
  private lastLoudAt = 0;
  private timer: number | null = null;
  private cb: RecorderCallbacks = {};
  level = 0;

  get recording(): boolean {
    return this.ctx !== null;
  }

  async start(cb: RecorderCallbacks = {}): Promise<void> {
    if (this.ctx) return;
    this.cb = cb;
    this.chunks = [];
    this.level = 0;

    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.ctx = new AudioContext();
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.processor = this.ctx.createScriptProcessor(FRAME, 1, 1);
    this.processor.onaudioprocess = (e) => {
      const data = e.inputBuffer.getChannelData(0);
      this.chunks.push(new Float32Array(data)); // copy — the buffer is reused
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
      this.level = Math.sqrt(sum / data.length);
      if (this.level >= SPEECH_RMS) this.lastLoudAt = Date.now();
    };
    this.source.connect(this.processor);
    // Output buffer is left at zeros, so nothing echoes back to the mic.
    this.processor.connect(this.ctx.destination);

    this.startedAt = Date.now();
    this.lastLoudAt = 0; // no speech heard yet
    this.timer = window.setInterval(() => this.checkEndpoint(), 120);
  }

  private checkEndpoint(): void {
    const now = Date.now();
    const heard = now - this.startedAt;
    if (heard >= MAX_RECORD_MS) {
      void this.finish("max");
      return;
    }
    // Auto-end only after real speech: silence before the first word is just
    // the user reaching for the button.
    if (this.lastLoudAt > 0 && heard >= MIN_SPEECH_MS && now - this.lastLoudAt >= SILENCE_END_MS) {
      void this.finish("silence");
    }
  }

  private async finish(reason: StopReason): Promise<void> {
    const blob = await this.stop();
    if (blob) this.cb.onEnd?.(blob, reason);
  }

  /** Stops capture and resolves with the WAV blob (null if not recording). */
  async stop(): Promise<Blob | null> {
    if (this.timer !== null) {
      window.clearInterval(this.timer);
      this.timer = null;
    }
    const ctx = this.ctx;
    if (!ctx) return null;
    this.ctx = null;
    try {
      this.processor?.disconnect();
      this.source?.disconnect();
      this.stream?.getTracks().forEach((t) => t.stop());
      await ctx.close();
    } catch {
      /* teardown races are harmless */
    }
    const blob = encodeWav(this.chunks, ctx.sampleRate);
    this.chunks = [];
    this.level = 0;
    return blob;
  }
}

/** Encode captured mono Float32 frames as a 16-bit PCM WAV. */
export function encodeWav(chunks: Float32Array[], sampleRate: number): Blob {
  let length = 0;
  for (const c of chunks) length += c.length;
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  const str = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };
  str(0, "RIFF");
  view.setUint32(4, 36 + length * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  str(36, "data");
  view.setUint32(40, length * 2, true);
  let offset = 44;
  for (const chunk of chunks) {
    for (let i = 0; i < chunk.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, chunk[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
  }
  return new Blob([buffer], { type: "audio/wav" });
}
