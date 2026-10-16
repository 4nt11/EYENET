---
name: eyenet-design
description: Use this skill to generate well-branded interfaces and assets for EYENET, a forensic observation console for analyzing threat actors, either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the README.md file within this skill, and explore the other available files.
If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.
If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.

Key rules for EYENET (see README.md for full detail):
- Three colors on black only: near-black surfaces, purple accent (`#743093` / `#a259c4`), one muted red (`#c2453f` / `#e07b76`). Red is reserved for alerts, top-tier classification, destructive actions, and tamper/error states.
- Monospace (JetBrains Mono) for ALL evidence — IDs, hashes, timestamps, data tables. System sans for UI chrome and prose.
- Flat and dark: 4px radius, 1px hairline borders as the only elevation. No gradients, glow, or shadows. No emoji.
- Dense, evidence-grade, calm. Legibility first; earn every pixel.
