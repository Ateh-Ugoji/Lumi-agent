import { request } from "./http.ts";

/** Upload a recorded WAV for transcription. Throws an `ApiError` with the server's message. */
export async function transcribeWav(blob: Blob): Promise<string> {
  const form = new FormData();
  form.append("file", blob, "clip.wav");
  const data = await request<{ text: string }>("/voice/transcribe", { method: "POST", form });
  return data.text;
}
