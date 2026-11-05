/**
 * Block-level markdown for agent replies.
 *
 * The agent writes GFM: `###` headings, `---` rules, `*` bullets (often with
 * nested items), `1.` steps, `>` quotes and fenced code. The chat bubble only
 * handled inline `**bold**`, so every block marker leaked through as literal
 * text ("### 👤 Archetype").
 *
 * Parsing lives here, without JSX, so it can be unit-tested under
 * `node --test` (which strips types but cannot transform TSX).
 */

export type MdInline =
  | { kind: "text"; text: string }
  | { kind: "strong"; text: string }
  | { kind: "em"; text: string }
  | { kind: "code"; text: string }
  | { kind: "link"; text: string; href: string };

export type MdListItem = {
  text: string;
  /** Leading spaces before the marker, so nested items keep their depth. */
  indent: number;
};

export type MdBlock =
  | { kind: "heading"; level: number; text: string }
  | { kind: "rule" }
  | { kind: "code"; lang: string; text: string }
  | { kind: "quote"; text: string }
  | { kind: "list"; ordered: boolean; items: MdListItem[] }
  | { kind: "paragraph"; text: string };

const HEADING = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^ {0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$/;
const QUOTE = /^ {0,3}>\s?(.*)$/;
const BULLET = /^(\s*)[*+-]\s+(.*)$/;
const ORDERED = /^(\s*)\d{1,9}[.)]\s+(.*)$/;
const FENCE = /^ {0,3}(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/;

/**
 * Inline tokens: `**strong**`, `` `code` ``, `[label](url)` and `*em*`.
 *
 * Bold is tried before emphasis, `*` is ignored when it touches a word (so
 * `a*b` and `listening_keywords` stay literal), and an opening `*` may not be
 * followed by a space (so `2 * 3` never opens emphasis).
 */
const INLINE =
  /(\*\*(?!\s)([^*\n]+?)(?<!\s)\*\*|`([^`\n]+)`|\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)|(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*]))/g;

export function parseInline(source: string): MdInline[] {
  const text = source ?? "";
  const out: MdInline[] = [];
  const re = new RegExp(INLINE.source, "g");
  let last = 0;
  let match: RegExpExecArray | null;

  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      out.push({ kind: "text", text: text.slice(last, match.index) });
    }
    if (match[2] !== undefined) out.push({ kind: "strong", text: match[2] });
    else if (match[3] !== undefined) out.push({ kind: "code", text: match[3] });
    else if (match[4] !== undefined) {
      out.push({ kind: "link", text: match[4], href: match[5] });
    } else if (match[6] !== undefined) out.push({ kind: "em", text: match[6] });

    last = match.index + match[0].length;
  }

  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

const startsBlock = (line: string): boolean =>
  HEADING.test(line) ||
  RULE.test(line) ||
  QUOTE.test(line) ||
  BULLET.test(line) ||
  ORDERED.test(line) ||
  FENCE.test(line);

export function parseMarkdown(source: string): MdBlock[] {
  const lines = (source ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks: MdBlock[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    const fence = FENCE.exec(line);
    if (fence) {
      const marker = fence[1];
      const lang = fence[2] ?? "";
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith(marker)) {
        body.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1; // closing fence
      blocks.push({ kind: "code", lang, text: body.join("\n") });
      continue;
    }

    if (!line.trim()) {
      i += 1;
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({
        kind: "heading",
        level: heading[1].length,
        text: heading[2],
      });
      i += 1;
      continue;
    }

    // `---` must be tested before bullets: it also starts with `-`.
    if (RULE.test(line)) {
      blocks.push({ kind: "rule" });
      i += 1;
      continue;
    }

    const quote = QUOTE.exec(line);
    if (quote) {
      const body: string[] = [quote[1]];
      i += 1;
      while (i < lines.length) {
        const next = QUOTE.exec(lines[i]);
        if (!next) break;
        body.push(next[1]);
        i += 1;
      }
      blocks.push({ kind: "quote", text: body.join("\n") });
      continue;
    }

    const orderedMatch = ORDERED.exec(line);
    const bulletMatch = orderedMatch ? null : BULLET.exec(line);
    if (orderedMatch || bulletMatch) {
      const ordered = orderedMatch !== null;
      const items: MdListItem[] = [];
      while (i < lines.length) {
        const m = ordered ? ORDERED.exec(lines[i]) : BULLET.exec(lines[i]);
        if (!m) break;
        const indent = m[1].replace(/\t/g, "  ").length;
        let text = m[2];
        i += 1;
        // Indented, non-marker lines belong to the item above them.
        while (i < lines.length) {
          const cont = lines[i];
          if (!cont.trim() || startsBlock(cont)) break;
          if (!/^\s{2,}/.test(cont)) break;
          text += ` ${cont.trim()}`;
          i += 1;
        }
        items.push({ text: text.trim(), indent });
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }

    const body: string[] = [line];
    i += 1;
    while (i < lines.length) {
      const next = lines[i];
      if (!next.trim() || startsBlock(next)) break;
      body.push(next);
      i += 1;
    }
    blocks.push({ kind: "paragraph", text: body.join("\n") });
  }

  return blocks;
}
