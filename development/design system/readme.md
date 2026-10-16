# EYENET Design System

A forensic observation console for analyzing threat actors. EYENET is an **operator tool** for a small team (often one person): information-dense, evidence-grade, calm under pressure. It is not a consumer SaaS dashboard and not enterprise bloat — think a serious analyst's terminal that happens to be a web app.

**Design north stars:** legibility at high density · restraint (three colors, earn every pixel) · accessible contrast on black · simple over decorative.

## Sources
Built from a written brief only — no codebase, Figma file, or existing product screens were provided. All values (palette, type, spacing, component inventory) are specified in that brief and encoded here as tokens. There is **no logo asset**; the wordmark "EYENET" is rendered in JetBrains Mono wherever a mark would sit (see Iconography). If a real logo exists, drop it in `assets/` and replace the type lockups.

## Palette — strictly three colors on black
Never introduce colors beyond these.

- **Base / background:** pure black `#000000`, with near-black layering surfaces `--surface #0c0d10`, `--panel #141519`, `--panel-2 #1a1c21`; hairline borders `--border #24262b`.
- **Brand accent — purple:** `--accent #743093` (fills, primary buttons), `--accent-text #a259c4` (text, links, hover/active).
- **Signal — red:** one muted red that sits calmly on black — `--red #c2453f` (destructive), `--red-text #e07b76` (critical text). **Reserved** for alerts, the top classification tier, destructive actions, and tamper/error states. Nothing else.
- **Text:** `--text #dfe5e5` primary, `--text-muted #9aa0aa` secondary, `--text-faint #7a7d8c` faint.

Flat and dark. `4px` radius everywhere. No gradients, no glow, no drop shadows — a 1px hairline border is the only elevation.

## Type
- **Monospace (`JetBrains Mono`)** for ALL evidence: IDs, hashes, timestamps, indicators, and data tables. Slight negative tracking (`--tracking-data`).
- **System sans** for UI chrome and prose. Uppercase micro-labels use positive tracking (`--tracking-label`).

## Content fundamentals
- **Tone:** terse, factual, present-tense. Machine-adjacent but human-authored. No marketing voice, no exclamation, no hedging.
- **Voice / person:** impersonal and operational — the system reports, the operator acts. Avoid "you"; prefer imperative verbs ("Reclassify", "Seal & purge") and neutral system statements ("Outbound C2 beacon detected").
- **Casing:** Sentence case for titles and prose. UPPERCASE (with letter-spacing) for micro-labels, tiers, and status badges (`CRITICAL`, `TAMPER`, `STREAMING`). Monospace tokens keep their literal casing.
- **Identifiers:** structured and monospace — `CASE-2026-0417`, `ART-0091`, `UNC-3312`, `T1071.001`, `2026-09-20 12:04:51Z`. Timestamps are UTC with a trailing `Z`.
- **Numbers & units:** exact, never rounded for flavor (`42 MB`, `185.12.44.9`). Counts get plain labels ("7 open leads").
- **No emoji.** Ever. Status is carried by a small colored dot, a hairline rail, or an uppercase badge — never a glyph with personality.
- **Vibe:** a calm evidence log. If a sentence sounds excited, rewrite it.

## Visual foundations
- **Backgrounds:** pure black app canvas; panels/surfaces are near-black steps (`--surface` → `--panel` → `--panel-2`) for layering. No images, no gradients, no textures, no patterns.
- **Borders:** 1px hairlines (`--border`, `--border-strong`) separate everything. This is the entire elevation system — there are no shadows.
- **Radius:** `4px` on containers/buttons, `2px` on badges. Nothing fully rounded except status dots.
- **Cards:** a hairline border + a near-black fill (`--panel`). Selected/active state = `--accent` border + a translucent purple fill (`--accent-fill`), never a shadow.
- **Color vibe:** cool, dark, flat. Accent purple is used sparingly for state and primary action; red is rationed to genuine signal.
- **Animation:** minimal and functional. 120ms ease on hover/background transitions; a ~900ms fade for a freshly-streamed feed item (purple flash → transparent). No bounces, no slides, no decorative motion.
- **Hover states:** surfaces lighten one step (`--panel` → `--panel-2`); primary/destructive buttons shift to their `-hover` tint. Rows get a `--panel` wash.
- **Press/active/selected:** purple border + `--accent-fill` wash and a 2px accent left-rail on selected table rows. No scale transforms.
- **Transparency & blur:** translucency only for the purple/red *fill* tints (selection, tamper, fresh-event). No blur, no glass.
- **Layout:** fixed top bar (44px) + fixed caseload sidebar (320px) + a flexible main column that owns its own scroll regions. Density first — 28–32px row heights, 6–8px cell padding.
- **Focus:** `--focus-ring` (translucent purple) for keyboard focus.

## Iconography
- **No custom icon set and no icon font** ship with this system, and none was provided. Status and meaning are carried **typographically**: colored status dots, uppercase mono labels, hairline rails, and tier badges — not pictograms.
- **No emoji, no decorative unicode.** A neutral dot (`•`), an arrow (`→`) inside monospace strings, and the `Z` timestamp suffix are the only glyph-level flourishes.
- If a consuming project needs true icons, add a **Lucide** (CDN) set at 1.5px stroke to match the hairline aesthetic and document the addition here. Until then, don't hand-draw SVGs.
- **Logo:** none provided. The "EYENET" wordmark in JetBrains Mono, letter-spaced `.16em`, is the stand-in mark. Replace with a real asset in `assets/` when available.

## Components
Reusable primitives (React, styled entirely via the CSS custom properties). Import from the compiled bundle namespace.

- **Button** (`components/actions/`) — primary (purple), destructive (red), ghost, quiet; sm/md/lg; optional icon.
- **Badge** (`components/status/`) — classification tier / status pill; `critical` is the only red tone; optional status dot.
- **DataTable** (`components/data/`) — dense evidence table; per-column mono, alignment, custom render; selectable rows.
- **EvidencePanel** (`components/data/`) — key/value panel with a fixed label column; monospace values; accent/critical tints.
- **CaseCard** (`components/console/`) — case summary card with id, title, tier badge, meta; active state.
- **EventFeedItem** (`components/console/`) — streaming live-event row; kind rail (info/observe/alert/system); `fresh` flash.
- **AuditRow** (`components/console/`) — immutable audit-trail row; verb/target/detail; `tamper` turns it red.

*Intentional additions:* none — the component set maps 1:1 to the brief's requested inventory.

## UI kits
- **`ui_kits/eyenet/`** — the assembled **case view**: fixed top bar, caseload sidebar (`CaseCard`s), and a case workspace combining the evidence `DataTable`, a `EvidencePanel` for the selected artifact, a **live streaming** event feed, and an immutable audit trail. Demonstrates the system in use; the feed streams new events on a timer.

## Index / manifest
- `styles.css` — root entry; `@import`s the token + font files only.
- `tokens/` — `colors.css`, `typography.css`, `spacing.css`, `fonts.css`.
- `components/` — `actions/`, `status/`, `data/`, `console/` (each: `.jsx`, `.d.ts`, `.prompt.md`, one `@dsCard` HTML).
- `guidelines/` — foundation specimen cards (Colors, Type, Spacing).
- `ui_kits/eyenet/` — case-view recreation (`index.html` + JSX).
- `thumbnail.html` — homepage tile.
- `SKILL.md` — Agent-Skill wrapper.

## Caveats
- **Fonts:** JetBrains Mono is loaded from the jsDelivr/fontsource CDN via `@font-face` (needs network). If you want the binaries vendored into `assets/`, provide them or say so. UI sans is the platform system stack by design.
- **No logo / brand assets** were provided; the type wordmark stands in. Supply a real mark to replace it.
