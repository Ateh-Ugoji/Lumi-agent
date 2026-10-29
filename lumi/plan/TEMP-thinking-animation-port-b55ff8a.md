# TEMP — Thinking-bar animation: port `b55ff8a` exactly

Status: **research + plan, no code yet.** Written 2026-10-29 on branch `Ateh-branch`.

Reference cloned to a new folder: `C:\Users\USER\Downloads\lumi-b55ff8a`
(shallow clone of `Ateh-Ugoji/Lumi`, both reference commits fetched):

| commit | date | what it is |
|---|---|---|
| `b55ff8a` | 2026-10-11 | *feat(ui): stream live thinking steps via SSE and display sample peer posts in trace cards* — the **animation baseline** the user wants back |
| `c466c5d` | 2026-10-11 | *…chronic online X ui with avatars…* — the commit whose screenshots show **logos in the thinking rows** (they live in `ThinkingState.tsx`, a different component) |

---

## 1. What `b55ff8a` actually does (exact code, file:line)

All in `frontend/src/components/AgentThinking/AgentThinking.tsx` (336 lines) +
`AgentThinking.module.css` (329 lines) + `src/styles/animations.css`.

**a. Header icon states** (`AgentThinking.tsx:224-247`)

```
final                 → <Sparkle/>
kind === "social"     → <SocialIconCycler platforms={step.platforms} reduced/>
kind === "action"     → <span className={spinner} animation="spin 700ms linear infinite"/>
otherwise             → <Sparkle/>
```

**b. `SocialIconCycler` — the "ball morphs into the logo"** (`:40-76`)

- `order = shuffle(platforms)` recomputed only when the platform list changes.
- `setInterval(700 + rand(0..200) ms)` advancing `idx % order.length` (skipped when `reduced` or a single platform).
- Renders `<span key={name} className={iconSocial [iconSocialLight]}>` — **the `key` remounts the node on every swap**, and `.iconSocial` carries

```css
.iconSocial { width:17px; height:17px; border-radius:4px; overflow:hidden;
              animation: iconSwap 180ms ease-out both; }
@keyframes iconSwap { from {opacity:0; transform:scale(.8)} to {opacity:1; transform:scale(1)} }
```

  → each logo **pops in from 80% scale**. This is the animation the current build is missing.

**c. Status text** (`:265-276`): `activeText` = gradient shimmer, `animation: shimmer-text 1.4s linear infinite`
(background-position 200% → −200%), `key={activeStep.id}` so the node remounts per step;
`doneText` = plain. `.noMotion` when reduced.

**d. Expand/collapse** (`:250-320`): wrapper `minHeight:176` + `transition: min-height 400ms cubic-bezier(0.23,1,0.32,1)`;
panel uses `grid-template-rows: 0fr→1fr` + `opacity` with the same easing; the vertical `.traceLine`
animates `height` over `500ms` to `lineHeight - 2` (measured via `useLayoutEffect`).

**e. Rows** (`StepRow`, `:113-170`): entrance `animation: fade-up 320ms cubic-bezier(0.23,1,0.32,1) ${order*120}ms both`;
busy = `.spinner` (12px ring, `spin 700ms linear infinite`), done = `<Check/>`;
label = `.rowActiveText` (shimmer 1.4s) while active, `.rowPrimary` when settled;
then `meta`, `detail`, `samplePosts` cards.

**f. `prefers-reduced-motion`** kills `.activeText/.rowActiveText/.iconSocial` animations and the `transition`s.

**Row logos come from `c466c5d`, not `b55ff8a`:** `ThinkingState.tsx:311-324` renders
`[<span className={social|socialLight}>` + `SocialIcon size={x?13:17}]` before the row text, and its
`.social` CSS (`ThinkingState.module.css:236-245`) is **static 17px, no keyframes** — which is what the
already-landed chip implementation mirrors.

---

## 2. What the current build does instead (the deltas)

| aspect | `b55ff8a` reference | current `Ateh-branch` |
|---|---|---|
| logo swap | `iconSwap` **pop**, 180ms, scale 0.8→1 | `iconOut/iconIn` crossfade keyframes (`AgentThinking.module.css:59-66`) — no scale pop |
| header busy mark | 12px CSS ring, `spin 700ms` | `WorkingMark` component (20px, variants) |
| active label (header + row) | plain shimmer `1.4s` | `MorphLabel` → old/new label crossfade (`labelOut/labelIn`) + `ShimmerLabel` 1.6s |
| logo chip box | 17px | 20px |
| structure (traceGrid/traceLine/minHeight/fade-up/chevron) | — | **identical, already ported** |
| row logo chips | not present (only header) | present (from `c466c5d` pattern) — keep |

So the user is seeing: correct chips, but **the wrong motion** — a crossfade instead of the pop,
a morphing label instead of the steady shimmer, and a different busy mark.

---

## 3. Port plan (ordered, minimal diffs)

1. **CSS pop-in** — `AgentThinking.module.css`: add `@keyframes iconSwap` and
   `animation: iconSwap 180ms ease-out both` on `.iconSocial`; resize `.iconSocial` 20px → 17px.
   One rule, restores the signature logo motion (it applies to both header cycler and row chips).
2. **Cycler remount** — `SocialIconCycler` in `AgentThinking.tsx`: render `<span key={name}>` so each
   swap remounts and re-runs `iconSwap`; keep `shuffle` + `700+rand(200)ms` cadence and the
   `reduced`/single-platform guards (verify current `iconOut/iconIn` path is removed, not stacked on top).
3. **Busy mark** — replace the active-row `WorkingMark` with the reference `.spinner`
   (12px ring, `spin 700ms linear infinite`), header `.spinner` for `kind==="action"` likewise.
4. **Label animation** — restore reference `activeText`/`rowActiveText` shimmer 1.4s (drop `MorphLabel`
   from rows and header, keep `key={step.id}` remount).
   ⚠️ Decision point: on 2026-10-28 you asked to *"leave the shining slide thing"* — the shimmer **is**
   that shine, so step 4 only removes the **morph** between labels, not the shimmer itself. If you want
   the morph kept, skip 4 and ship 1–3 only.
5. **Keep** the row chips (they match `c466c5d`'s static `.social` exactly once resized to 17px) and
   keep the platform fix from this branch (`args.platform || activePlatform`).
6. **Verify** — `npx tsc -b`; live run confirming: chip pops in, cycler swaps with pop,
   busy ring spins, shimmer sweeps, rows fade-up staggered; check `prefers-reduced-motion`.

Effort: steps 1–2 are ~20 lines of CSS/TSX; 3–4 are small reverts; whole port ≈ 1 h including the visual pass.
