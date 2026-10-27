const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

/** Upload a recorded WAV to the backend for Groq Whisper transcription.
 *  Throws the server's honest error text on failure — the caller shows it. */
export async function transcribeWav(blob: Blob): Promise<string> {
  const form = new FormData();
  form.append("file", blob, "clip.wav");
  const res = await fetch(`${API_BASE}/voice/transcribe`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    let detail = res.statusText || String(res.status);
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  const data = (await res.json()) as { text: string };
  return data.text;
}
