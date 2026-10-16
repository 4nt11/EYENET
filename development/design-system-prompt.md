Set up a design system for **EYENET**, a forensic observation console for analyzing threat actors. It's an operator tool for a small team (often one person) — information-dense, evidence-grade, calm under pressure. Not a consumer SaaS dashboard, not enterprise bloat. Think: a serious analyst's terminal that happens to be a web app.

**Palette — strictly three colors on black. Do not introduce others.**
- Base / background: pure black `#000000`, with near-black surfaces for layering: `#0c0d10` (surface), `#141519` (panel), hairline borders `#24262b`.
- Brand accent: purple `#743093`, with `#a259c4` for text, links, and hover/active states.
- Signal: red — reserved for alerts, critical classification tiers, destructive actions, and tamper/error states. Pick one red that sits calmly on black (muted, not fire-engine).
- Text: `#dfe5e5` primary, `#9aa0aa` muted, `#7a7d8c` faint.
- Keep it flat and dark. `4px` radius. No gradients, no glow, no drop shadows beyond a subtle 1px border.

**Type**
- Monospace for all evidence, IDs, hashes, timestamps, and data tables (`JetBrains Mono`/`IBM Plex Mono`).
- System sans for UI chrome and prose.

**Deliver as a design system:**
1. Color, type, spacing, and radius tokens (CSS custom properties, dark-first — this UI is never light).
2. Core components an operator console needs: dense data tables, status/tier badges (use red only for the top severity), audit-trail rows, case cards, live event feed items (streaming), key/value evidence panels, and buttons (primary = purple, destructive = red, everything else quiet/ghost).
3. One example screen assembling them — a case view with a live event feed and an evidence table — so the system is shown in use.

Priorities: legibility at high density, restraint (three colors, earn every pixel), and accessible contrast on black. Simple over decorative.
