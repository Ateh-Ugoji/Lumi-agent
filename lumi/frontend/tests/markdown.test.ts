import assert from "node:assert/strict";
import { test } from "node:test";
import { parseInline, parseMarkdown } from "../src/markdown.ts";

test("headings lose their markers and keep their level", () => {
  const blocks = parseMarkdown("### 👤 Archetype: Reflective Startup Marketer");
  assert.equal(blocks.length, 1);
  assert.deepEqual(blocks[0], {
    kind: "heading",
    level: 3,
    text: "👤 Archetype: Reflective Startup Marketer",
  });
});

test("a horizontal rule is not mistaken for a bullet", () => {
  assert.deepEqual(parseMarkdown("---"), [{ kind: "rule" }]);
});

test("bullets keep text and nesting depth", () => {
  const blocks = parseMarkdown(
    [
      "*   Perspective & Tone: Casual, candid.",
      "*   Structure & Formatting:",
      "    *   Length: 30–80 words.",
      "    *   Layout: Short paragraphs.",
    ].join("\n"),
  );
  assert.deepEqual(blocks, [
    {
      kind: "list",
      ordered: false,
      items: [
        { text: "Perspective & Tone: Casual, candid.", indent: 0 },
        { text: "Structure & Formatting:", indent: 0 },
        { text: "Length: 30–80 words.", indent: 4 },
        { text: "Layout: Short paragraphs.", indent: 4 },
      ],
    },
  ]);
});

test("ordered lists and quotes parse as their own blocks", () => {
  const blocks = parseMarkdown(
    ["1. First step", "2) Second step", "", "> quoted line"].join("\n"),
  );
  assert.deepEqual(blocks, [
    {
      kind: "list",
      ordered: true,
      items: [
        { text: "First step", indent: 0 },
        { text: "Second step", indent: 0 },
      ],
    },
    { kind: "quote", text: "quoted line" },
  ]);
});

test("fenced code keeps its body verbatim", () => {
  const blocks = parseMarkdown("```ts\nconst a = 1;\n\nconst b = 2;\n```");
  assert.deepEqual(blocks, [
    { kind: "code", lang: "ts", text: "const a = 1;\n\nconst b = 2;" },
  ]);
});

test("a heading glued to prose still splits the paragraph", () => {
  const blocks = parseMarkdown(
    ["### 🎨 Voice Breakdown", "", "Creator Bio Summary: marketer."].join("\n"),
  );
  assert.deepEqual(blocks, [
    { kind: "heading", level: 3, text: "🎨 Voice Breakdown" },
    { kind: "paragraph", text: "Creator Bio Summary: marketer." },
  ]);
});

test("inline emphasis, code and links tokenise", () => {
  assert.deepEqual(parseInline("mix marketing (*B2C, conversion*) with “fire”"), [
    { kind: "text", text: "mix marketing (" },
    { kind: "em", text: "B2C, conversion" },
    { kind: "text", text: ") with “fire”" },
  ]);
  assert.deepEqual(parseInline("**Never** do `this`"), [
    { kind: "strong", text: "Never" },
    { kind: "text", text: " do " },
    { kind: "code", text: "this" },
  ]);
  assert.deepEqual(parseInline("see [docs](https://example.com/x)"), [
    { kind: "text", text: "see " },
    { kind: "link", text: "docs", href: "https://example.com/x" },
  ]);
});

test("snake_case and arithmetic stay literal", () => {
  assert.deepEqual(parseInline("listening_keywords"), [
    { kind: "text", text: "listening_keywords" },
  ]);
  assert.deepEqual(parseInline("2 * 3 * 4"), [{ kind: "text", text: "2 * 3 * 4" }]);
});

test("the pasted voice audit no longer leaks block markers", () => {
  const audit = [
    "Here is the audit of your creator voice profile:",
    "",
    "### 👤 Archetype: Reflective Startup Marketer",
    "Creator Bio Summary: A marketing professional turned developer.",
    "",
    "---",
    "",
    "### 🎨 Voice Breakdown",
    "",
    "*   Perspective & Tone: Written strictly in the first person.",
    "*   Emoji Use: Occasional and purposeful (e.g., 😂, 🫶).",
    "",
    "### 🚫 Things You Never Do",
    "*   No formal salutations.",
    "",
    "### 💬 Representative Excerpts",
    '> *"Crazy how I never thought I will be so dev inclined"*',
  ].join("\n");

  const blocks = parseMarkdown(audit);
  assert.deepEqual(
    blocks.map((b) => b.kind),
    [
      "paragraph",
      "heading",
      "paragraph",
      "rule",
      "heading",
      "list",
      "heading",
      "list",
      "heading",
      "quote",
    ],
  );

  const text = JSON.stringify(blocks);
  assert.ok(!text.includes("###"), "no heading marker survives");
  assert.ok(!text.includes("*   "), "no bullet marker survives");
});
