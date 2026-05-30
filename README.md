<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# EYENET

Observation framework for **forensic analysis of threat actors**. EYENET
consumes [BEHAVE-TEXT](../BEHAVE/BEHAVE-TEXT) behavioral primitives and is a
sibling of DECNET. It is built for **small operators** — the analyst running a
few collectors, not an enterprise SOC — and takes an **operator-grade evidence**
posture: retain full content, audit every access, never hobble the operator.

> **Status:** pre-public (no migrations yet; schema changes are
> `rm data/*.db && eyenet init`). Milestones M1–M9 shipped; **M10 — Document
> Classifier** is in progress. See [`PLAN.md`](PLAN.md) for the roadmap and
> [`CLAUDE.md`](CLAUDE.md) for architecture and conventions.

---

## Requirements

- **Python ≥ 3.12**
- **Linux** — required for the M10 document-classifier extraction sandbox
  (it relies on Linux namespaces + seccomp via nsjail). The rest of EYENET is
  portable, but sensitive-evidence deployments are Linux-only by design.
- The sibling specs `behave-core` and `behave-text` are path-editable
  (`../BEHAVE/...`); check them out alongside this repo. The toolchain is
  [`uv`](https://docs.astral.sh/uv/).

## Installation

### Core

```bash
uv sync                 # runtime deps from [project.dependencies]
uv sync --extra dev     # + test / lint / type / security toolchain
```

The Spanish spaCy model `es_core_news_sm` (~13 MB) auto-fetches on first run for
the locale-aware primitives — see [`CLAUDE.md`](CLAUDE.md) §5.

### Document Classifier (M10) — extraction sandbox

The classifier assigns a sensitivity tier to incoming evidence at reception.
Document **parsing is a security boundary**: attacker-controlled files are parsed
only inside an [nsjail](https://github.com/google/nsjail) cage whose containment
is re-proven on every boot. These dependencies are **deliberately isolated** from
the main application environment.

**1. System binaries** (not pip-installable):

| Binary | Purpose | Fedora | Debian/Ubuntu |
|---|---|---|---|
| `nsjail` | the extraction sandbox | build from [source](https://github.com/google/nsjail) → `/usr/local/bin/nsjail` | build from source |
| `tesseract` | OCR engine | `dnf install tesseract` | `apt install tesseract-ocr` |

**2. The dedicated `eyenet-extract` venv** — the parser libraries
(`pymupdf`, `python-docx`, `pytesseract`, `presidio-analyzer`) live in the
`extract` optional-dependency group, **not** in the core deps. They are installed
into a *separate, minimal* virtualenv that is bound **read-only** into the jail,
so a parser exploit can never reach the main app's dependency tree:

```bash
python -m venv /opt/eyenet/extract-venv
/opt/eyenet/extract-venv/bin/pip install 'eyenet[extract]'
```

**3. Pre-fetch models on the host.** The jail has **no network**, so model data
cannot download inside it. Provision before first classification:

- the spaCy model used by Presidio (e.g. `es_core_news_sm`), and
- Tesseract language data (`tessdata`) for the languages you OCR.

If nsjail is absent or too old, or the sandbox cannot prove containment at boot,
the classifier runs **degraded fail-closed**: every document is assigned the
highest sensitivity tier pending operator review. Under-classification is never
silent. Design detail: [`development/CLASSIFIER_PLAN.md`](development/CLASSIFIER_PLAN.md).

## Documentation

| Doc | What |
|---|---|
| [`PLAN.md`](PLAN.md) | milestone roadmap (M1–M10) |
| [`development/API_PLAN.md`](development/API_PLAN.md) | M9 HTTP API spec (source of truth for v1 routes) |
| [`development/MODELS.md`](development/MODELS.md) | table-by-table schema reference |
| [`development/CLASSIFIER_PLAN.md`](development/CLASSIFIER_PLAN.md) | M10 Document Classifier design + build plan |
| [`CLAUDE.md`](CLAUDE.md) | architecture, conventions, and traps |

## License

AGPL-3.0-or-later.
