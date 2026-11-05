/** Browser-local TTS for agent replies.
 *
 *  No TTS provider key exists yet (Groq exposes no TTS model on this account —
 *  see docs/codenamejo-integration.md §3.1), so replies are spoken by the
 *  browser. Replies are split into sentence-sized phrases (Codename Jo's
 *  phrase-buffered pattern) so speech starts immediately and a new recording
 *  can interrupt instantly: barge-in cancels speech, never the agent run.
 */

let generation = 0;

function phrases(text: string): string[] {
  return (text.match(/[^.!?…\n]+[.!?…]*\s*/g) ?? [])
    .map((p) => p.trim())
    .filter(Boolean)
    .slice(0, 60);
}

export function stopSpeaking(): void {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  generation += 1;
  window.speechSynthesis.cancel();
}

/** Speaks the text; returns false when TTS is unavailable or text is empty. */
export function speak(text: string): boolean {
  if (typeof window === "undefined" || !window.speechSynthesis) return false;
  stopSpeaking();
  const parts = phrases(text);
  if (parts.length === 0) return false;

  const gen = generation;
  let i = 0;
  // Chrome can stall long speech sessions; a periodic resume keeps it moving.
  const keepalive = window.setInterval(() => {
    if (gen !== generation) {
      window.clearInterval(keepalive);
      return;
    }
    if (window.speechSynthesis.paused) window.speechSynthesis.resume();
  }, 8000);

  const next = () => {
    if (gen !== generation || i >= parts.length) {
      window.clearInterval(keepalive);
      return;
    }
    const utterance = new SpeechSynthesisUtterance(parts[i++]);
    utterance.onend = next;
    utterance.onerror = next; // an interrupted phrase must not strand the rest
    window.speechSynthesis.speak(utterance);
  };
  next();
  return true;
}
