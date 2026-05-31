"""``eyenet calibrate classify`` — document-classifier calibration subcommands.

Two subcommands, split by their dependency on the jail (CLASSIFIER_PLAN §slice-9):

* ``capture`` — JAIL-GATED. Runs the real Presidio NER pass over each corpus
  sample and writes the raw findings to a sidecar JSONL. Needs nsjail + the
  ABI-matched ``eyenet-extract`` venv (es/en spaCy models). Run ONCE per corpus.
* ``run``     — OFFLINE. Loads the corpus + the captured findings sidecar, runs
  the document grid (regex in-process + ``map_findings`` over the sidecar),
  scores it, and writes the hash-pinned calibration artifact. No jail.

The headline metric is the under-classification (false-negative) rate — the one
catastrophic error direction (§0). ``run`` echoes it prominently.

Operator-driven, not part of the production runtime (mirrors ``eyenet
calibrate run``). The committed baseline + its regression test are the
artifacts; these commands regenerate them.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import typer

from eyenet.classifier.presidio import detect_findings, load_pii_map
from eyenet.classifier.ruleset import load_ruleset
from eyenet.classifier.sandbox import arm_sandbox

from . import classifier_artifact, document_grid
from .document_corpus import load_document_corpus, load_findings, sha256_file

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command("capture")
def cmd_capture(  # pragma: no cover  (jail-gated; proven by the real-jail smoke)
    corpus: Path = typer.Option(..., "--corpus", help="document corpus JSONL"),
    out: Path = typer.Option(..., "--out", help="findings sidecar JSONL to write"),
) -> None:
    """Capture raw Presidio findings per sample through the real jail.

    Requires nsjail + the eyenet-extract venv. A sample whose jailed pass
    fails (venv absent, OOM/timeout/seccomp kill, bad envelope) is reported and
    SKIPPED — fix the jail and re-run; never ship a sidecar with silent gaps,
    because a missing findings row would model a doc as having no PII and could
    mask an under-classification in the grid.
    """
    # Arm the chokepoint (boot canary) before any jailed pass — an unarmed gate
    # fails every extraction closed (CLASSIFIED), which would silently empty the
    # sidecar. A DEGRADED sandbox means containment could not be proven; refuse to
    # capture rather than ship findings from an unproven jail.
    verification = arm_sandbox()
    if not verification.ok:
        typer.echo(
            f"sandbox NOT healthy ({verification.failure_reason}) — refusing to "
            "capture; fix nsjail + the extract venv first",
            err=True,
        )
        raise typer.Exit(code=1)

    samples = load_document_corpus(corpus)
    typer.echo(f"loaded {len(samples)} samples from {corpus}")
    rows: list[dict[str, object]] = []
    failed: list[str] = []
    for s in samples:
        findings = detect_findings(s.text)
        if findings is None:
            failed.append(s.doc_id)
            typer.echo(f"  FAIL (jail) {s.doc_id} — skipped", err=True)
            continue
        rows.append({"doc_id": s.doc_id, "findings": [asdict(f) for f in findings]})
        typer.echo(f"  ok {s.doc_id}: {len(findings)} findings")

    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    typer.echo(f"wrote sidecar: {out} ({len(rows)} docs)")
    if failed:
        typer.echo(f"WARNING: {len(failed)} docs failed the jail: {failed}", err=True)
        raise typer.Exit(code=1)


@app.command("run")
def cmd_run(  # pragma: no cover  (operator-driven; grid + artifact logic unit-tested)
    corpus: Path = typer.Option(..., "--corpus", help="document corpus JSONL"),
    findings: Path = typer.Option(..., "--findings", help="captured findings sidecar JSONL"),
    out: Path = typer.Option(..., "--out", help="calibration artifact JSON to write"),
    labeler: str = typer.Option("operator", "--labeler", help="who labeled the corpus"),
    corpus_id: str = typer.Option("", "--corpus-id", help="defaults to corpus filename stem"),
) -> None:
    """Run the offline document grid and write the hash-pinned artifact."""
    if not corpus.exists():
        typer.echo(f"corpus not found: {corpus}", err=True)
        raise typer.Exit(code=1)
    if not findings.exists():
        typer.echo(f"findings sidecar not found: {findings}", err=True)
        raise typer.Exit(code=1)

    samples = load_document_corpus(corpus)
    findings_by_doc = load_findings(findings)
    known = {s.doc_id for s in samples}
    stale = sorted(set(findings_by_doc) - known)
    if stale:
        typer.echo(f"findings sidecar references unknown doc_ids: {stale}", err=True)
        raise typer.Exit(code=1)

    grid = document_grid.run(
        samples,
        findings_by_doc,
        ruleset=load_ruleset(),
        pii_map=load_pii_map(),
    )
    artifact = classifier_artifact.build(
        grid,
        corpus_id=corpus_id or corpus.stem,
        corpus_sha256=sha256_file(corpus),
        n_finding_docs=len(findings_by_doc),
        labeler=labeler,
    )
    self_hash = classifier_artifact.write(artifact, out)

    typer.echo(f"\nwrote artifact: {out}")
    typer.echo(f"self_hash: {self_hash}")
    typer.echo(f"samples: {grid.n_samples}")
    typer.secho(
        f"UNDER-classification rate (HEADLINE, §0): {grid.under_classification_rate:.3f}",
        fg=typer.colors.RED if grid.under_classification_rate > 0 else typer.colors.GREEN,
    )
    typer.echo(f"over-classification rate:  {grid.over_classification_rate:.3f}")
    typer.echo(f"exact-match rate:          {grid.exact_match_rate:.3f}")
    typer.echo(
        f"recommended density: restricted_at={grid.recommended_restricted_at} "
        f"classified_at={grid.recommended_classified_at}"
    )


__all__ = ["app"]
