# TEMP — Social logos in the thinking bar while searching socials

Status: **plan + implementation.** Written 2026-10-28 on branch `Ateh-branch`.
Reference: old Lumi commit `c466c5d` (`Ateh-Ugoji/Lumi`), `frontend/src/components/ThinkingState/ThinkingState.tsx`.

## 1. Goal (what the reference shows)

In the old UI's thinking bar, the **rows themselves** carried the platform's logo: the
`Search`/`Social` variants rendered each row as `[logo chip] primary text …` — X's logo on
the x.com row, Instagram's on the instagram.com row, etc. The user wants that back:
*"if it's searching on facebook, the facebook logo showing."*

## 2. Current state (orquestador)

- The **header icon** already morphs: for `kind === "social"` steps the ball crossfades into
  a cycling platform logo (`SocialIconCycler`, `AgentThinking.tsx:29-65`, keyed
  `social:{platforms}` at `:402-404`), and account steps show the profile avatar
  (`AvatarIcon`). That was the earlier "ball → logo/avatar" work.
- The **rows** (`StepRow`, `AgentThinking.tsx:259-321`) show only
  `[Check/WorkingMark] label · meta` + optional `detail` + sample-post cards. **No logo.**
- The data is already there: every `tool_start` maps to a `SimStep` with
  `kind` + `platforms: string[]` (`App.tsx:727-800`):
  - `check_niche_trends` → `["x"]` (the X search)
  - `get_posts` / `get_analytics` / `get_user_activity` / `check_trending` / `backfill_posts`
    → `[activeProfile.platform]` (so **facebook** when the connected account is Facebook)
  - `discover_and_extract_niche_frameworks` → `["x", "linkedin"]`
  - `repurpose_caption` → `[target_platform]`
  - `extract_voice_profile` → `[activeProfile.platform]`
- `SocialIcons.tsx` exports all six needed marks: `x, facebook, instagram, linkedin,
  tiktok, youtube` (default export `SocialIcon({name, size})`).

## 3. Reference implementation (verbatim from c466c5d)

```tsx
{variant === "Search" || variant === "Social" ? (
  row.logo ? (
    <span className={`${styles.social} ${
      row.logo === "x" ? styles.socialLight : ""
    }`}>
      <SocialIcon name={row.logo} size={row.logo === "x" ? 13 : 17} />
    </span>
  ) : …
```

Rules distilled: **leading chip before the row text**; all platforms render at size 17 in a
20×20 rounded chip; the X mark is drawn smaller (13) on a **white** chip (`socialLight`)
because it is a solid black glyph.

The orquestador already has the exact same chip CSS in
`AgentThinking.module.css:387-403` (`.iconSocial` 20×20 radius-4 flex,
`.iconSocialLight` white background + 2px padding) — used today by `SocialIconCycler`.

## 4. The change

**File 1 — `frontend/src/components/AgentThinking/AgentThinking.tsx` (`StepRow`)**

Render a logo chip at the start of `.rowBody`'s first line when the step searches a social
network:

- Condition: `step.kind === "social" || step.kind === "analysis"` and
  `step.platforms?.length` → show the badge. (Action/writing steps stay clean.)
- Render **up to 3** platforms from `step.platforms`, in order, each as
  `<span className={iconSocial + iconSocialLight-for-x}><SocialIcon name={p} size={p==="x"?13:17}/></span>`.
  Real steps carry 1–2 platforms, so the row never crowds.
- Position: inside `.rowLine`, **before** the label (active `MorphLabel` or `rowPrimary`) —
  mirroring the reference's leading-chip layout; the Check/WorkingMark column stays first.
- Unknown platform names (defensive): skip rendering that chip rather than a broken glyph —
  `SocialIcon`'s `ICONS` lookup has no entry for e.g. `google`.
- `aria-hidden` on the chip (decorative; the label already says what is happening).

**File 2 — `frontend/src/components/AgentThinking/AgentThinking.module.css`**

Reuse `.iconSocial`/`.iconSocialLight` as-is if sizing fits the row (same 20px rhythm);
only add a `.rowLineSocial { gap: 6px }`-style alignment helper if the flex line needs it.
No new keyframes — the row's existing `fade-up` entrance covers the chip.

**No backend or `App.tsx` change** — the mapping (`kind`, `platforms`) already exists; this
is purely what `StepRow` draws.

## 5. Result per example

| Active search | Row shows |
|---|---|
| `check_niche_trends` ("Searching high-impression peer posts") | `𝕏` chip (x) |
| `get_posts` while the connected account is Facebook | facebook chip |
| `get_analytics` on LinkedIn | linkedin chip |
| `discover_and_extract_niche_frameworks` | x + linkedin chips |
| `connect_account` / `save_user_request` (kind `action`) | no chip — clean row |

## 6. Verification

1. `cd frontend && npm run build` (runs `tsc -b` + vite) → zero type errors.
2. Visual: start the stack, send a prompt that triggers a social tool; confirm the chip
   appears on active **and** settled rows, and that non-social steps stay chip-less.
3. Regression: header morph (ball → logo/avatar) still works — untouched code path.
