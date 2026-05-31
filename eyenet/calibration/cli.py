"""``eyenet calibrate`` CLI subcommand group.

Four subcommands:

* ``run``           — full grid → JSON artifact at ``--out``.
* ``label-helper``  — emit per-actor stats + msg samples for an operator to
                      label (writes a markdown file). Used when bootstrapping
                      a labels TOML against a new corpus.
* ``report``        — render a human-readable summary of an artifact JSON.
* ``diff``          — side-by-side delta between two artifacts (regression
                      triage when the grid produces different numbers).

The CLI is intentionally operator-driven, not automated. M5's calibration
artifact is committed; ``run`` is the regeneration entrypoint, not part of
the production runtime.
"""

from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

import typer

from .artifact import build, corpus_sha256, load, write
from .classifier_cli import app as classify_app
from .corpus import group_by_sender, iter_messages
from .interaction import ActorStats, compute_actor_stats, compute_all, write_csv
from .labels import assert_matches_corpus, load as load_labels
from .recipes_grid import render as render_recipes, run as run_recipes
from .simhash_grid import render_grid_result, run as run_simhash
from .verifier_grid import run as run_verifier_grid

app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(
    classify_app,
    name="classify",
    help="M10 document-classifier tier calibration (capture + run)",
)


def _read_stats_csv(path: Path) -> list[ActorStats]:
    rows: list[ActorStats] = []
    with path.open() as fh:
        for r in csv.DictReader(fh):
            rows.append(
                ActorStats(
                    sender_id=int(r["sender_id"]),
                    msg_count=int(r["msg_count"]),
                    corpus_span_days=float(r["corpus_span_days"]),
                    msg_per_day=float(r["msg_per_day"]),
                    init_rate=float(r["init_rate"]),
                    reply_rate=float(r["reply_rate"]),
                    mention_rate=float(r["mention_rate"]),
                    mean_msg_chars=float(r["mean_msg_chars"]),
                    median_msg_chars=float(r["median_msg_chars"]),
                    length_cv=float(r["length_cv"]),
                    inter_msg_p50=float(r["inter_msg_p50"]),
                    inter_msg_cv=float(r["inter_msg_cv"]),
                    mattr=float(r["mattr"]),
                )
            )
    return rows


@app.command("run")
def cmd_run(  # pragma: no cover
    corpus: Path = typer.Option(..., "--corpus", help="path to corpus JSONL"),
    labels: Path = typer.Option(..., "--labels", help="path to labels TOML"),
    out: Path = typer.Option(..., "--out", help="path to write artifact JSON"),
    stats_out: Path | None = typer.Option(
        None,
        "--stats-out",
        help="optional path to write per-actor stats CSV (re-derivable)",
    ),
    min_messages: int = typer.Option(
        50,
        "--min-messages",
        help="min text messages for simhash qualification",
    ),
    min_precision: float = typer.Option(
        0.70,
        "--min-precision",
        help="precision floor for threshold pickers",
    ),
    language: str = typer.Option(
        "es",
        "--language",
        help="language slice for simhash grid (calibrated only for es)",
    ),
    disable_simhash_lang: bool = typer.Option(
        True,
        "--disable-simhash-lang/--enable-simhash-lang",
        help="record this language slice as disabled in the artifact",
    ),
    corpus_id: str = typer.Option(
        "",
        "--corpus-id",
        help="artifact corpus_id; defaults to corpus filename stem",
    ),
    extra_sender: list[int] = typer.Option(
        [],
        "--extra-sender",
        help=(
            "sender_id to include in per-actor stats even if below "
            "--min-messages (use for known bots / sub-threshold positives). "
            "Repeatable."
        ),
    ),
) -> None:
    """Run the full calibration grid and write an artifact."""
    if not corpus.exists():
        typer.echo(f"corpus not found: {corpus}", err=True)
        raise typer.Exit(code=1)
    if not labels.exists():
        typer.echo(f"labels file not found: {labels}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"loading corpus: {corpus}")
    sha = corpus_sha256(corpus)
    typer.echo(f"  sha256: {sha}")

    labelset = load_labels(labels)
    assert_matches_corpus(labelset, sha)
    typer.echo(f"loaded {len(labelset.actors)} labels (corpus pin OK)")

    typer.echo(f"computing actor stats (min_messages={min_messages})...")
    msgs = list(iter_messages(corpus))
    grouped = group_by_sender(msgs, min_messages=min_messages)
    typer.echo(f"  {len(grouped)} actors qualifying for simhash")
    stats = compute_all(grouped)

    if extra_sender:
        existing = {s.sender_id for s in stats}
        for sid in extra_sender:
            if sid in existing:
                continue
            extra_msgs = [m for m in msgs if m.sender_id == sid]
            if not extra_msgs:
                typer.echo(f"  WARN: --extra-sender {sid} has no messages", err=True)
                continue
            extra_msgs.sort(key=lambda m: (m.ts, m.msg_id))
            stats.append(compute_actor_stats(extra_msgs))
            typer.echo(f"  added extra sender {sid} ({len(extra_msgs)} msgs)")

    if stats_out is not None:
        write_csv(stats, stats_out)
        typer.echo(f"wrote stats CSV: {stats_out}")

    typer.echo("running simhash grid (this hits the primitives)...")
    sh_grid = run_simhash(grouped, language_filter=language, min_precision=min_precision)
    typer.echo(render_grid_result(sh_grid))

    typer.echo("\nrunning recipe grid...")
    recipe_results = run_recipes(stats, labelset.by_sender, min_precision=min_precision)
    typer.echo(render_recipes(recipe_results))

    typer.echo("\nrunning verifier grid (M8)...")
    v_grid = run_verifier_grid(
        msgs,
        min_messages=min_messages,
        language=language,
        min_precision=min_precision,
    )
    typer.echo(f"verifier grid: {v_grid.actor_count} actors, {len(v_grid.per_verifier)} verifiers")
    for v in v_grid.per_verifier:
        typer.echo(
            f"  {v.verifier}: AUC={v.auc:.4f}  "
            f"chosen_t={v.chosen_threshold:.2f}  "
            f"P={v.chosen_precision:.3f}  R={v.chosen_recall:.3f}  F1={v.chosen_f1:.3f}"
        )

    cid = corpus_id or corpus.stem
    artifact = build(
        corpus_id=cid,
        corpus_sha256=sha,
        actor_count_total=len(stats),
        actor_count_simhash_qualifying=len(grouped),
        min_messages=min_messages,
        labeler=labelset.labeler,
        label_counts=labelset.counts(),
        simhash_grid=sh_grid,
        simhash_es_disabled=disable_simhash_lang,
        recipe_results=recipe_results,
        verifier_grid=v_grid,
        verifier_es_disabled=disable_simhash_lang,
        notes=(),
    )
    self_hash = write(artifact, out)
    typer.echo(f"\nwrote artifact: {out}")
    typer.echo(f"self_hash: {self_hash}")


@app.command("label-helper")
def cmd_label_helper(  # pragma: no cover
    corpus: Path = typer.Option(..., "--corpus", help="path to corpus JSONL"),
    out: Path = typer.Option(..., "--out", help="markdown output for operator labeling"),
    top: int = typer.Option(100, "--top", help="top-N senders by msg count"),
    min_messages: int = typer.Option(50, "--min-messages", help="floor for qualifying senders"),
    samples: int = typer.Option(10, "--samples", help="msg samples per actor (evenly spaced)"),
) -> None:
    """Emit per-actor stats + samples to a markdown file for operator labeling.

    Output is NOT a labels TOML; it's reading material. The operator (or
    Claude-as-labeler) reads this and hand-writes the labels file.
    """
    msgs = list(iter_messages(corpus))
    grouped = group_by_sender(msgs, min_messages=min_messages)
    typer.echo(f"qualifying actors: {len(grouped)}")

    sorted_actors = sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)[:top]
    lines: list[str] = []
    for sid, ms in sorted_actors:
        n = len(ms)
        stats = compute_actor_stats(ms)
        d = asdict(stats)
        lines.append(f"## sender_id={sid}")
        lines.append(
            f"msgs={n}  span_days={d['corpus_span_days']:.2f}  "
            f"init_rate={d['init_rate']:.3f}  mean_len={d['mean_msg_chars']:.1f}  "
            f"length_cv={d['length_cv']:.3f}  inter_msg_cv={d['inter_msg_cv']:.2f}  "
            f"mattr={d['mattr']:.3f}"
        )
        # Evenly spaced sample indices.
        idxs = sorted({(i * n) // samples for i in range(samples)}) if samples > 0 else []
        idxs = [i for i in idxs if 0 <= i < n]
        for i in idxs:
            t = ms[i].text.replace("\n", " ")[:160]
            lines.append(f"  [{i:5d}] {t}")
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"wrote: {out}")


@app.command("report")
def cmd_report(  # pragma: no cover
    artifact: Path = typer.Option(..., "--artifact", help="artifact JSON path"),
) -> None:
    """Render a markdown summary of a calibration artifact."""
    a, h = load(artifact)
    computed = a.compute_self_hash()
    hash_ok = "OK" if computed == h else "MISMATCH"
    typer.echo(f"# Calibration artifact: {a.corpus_id}")
    typer.echo("")
    typer.echo(f"- corpus_sha256: `{a.corpus_sha256}`")
    typer.echo(f"- self_hash: `{h}` ({hash_ok})")
    typer.echo(f"- generated_at: {a.generated_at}")
    typer.echo(f"- eyenet_version: {a.eyenet_version}")
    typer.echo(f"- behave_text_version: {a.behave_text_version}")
    typer.echo(f"- actors total: {a.actor_count_total}")
    typer.echo(f"- actors simhash-qualifying: {a.actor_count_simhash_qualifying}")
    typer.echo(f"- min_messages: {a.min_messages}")
    typer.echo(f"- labeler: {a.labeler}")
    typer.echo(f"- label_counts: {dict(a.label_counts)}")
    typer.echo("")
    typer.echo("## Simhash")
    typer.echo("")
    typer.echo("| primitive | lang | enabled | AUC | chosen_threshold | P | R | F1 |")
    typer.echo("|---|---|---|---|---|---|---|---|")
    for s in a.simhash:
        typer.echo(
            f"| {s.primitive} | {s.language} | {s.enabled} | {s.auc} | "
            f"{s.chosen_threshold} | {s.chosen_precision} | "
            f"{s.chosen_recall} | {s.chosen_f1} |"
        )
    typer.echo("")
    typer.echo("## Recipes")
    typer.echo("")
    typer.echo("| recipe | strategy | TP | FP | TN | FN | P | R | F1 |")
    typer.echo("|---|---|---|---|---|---|---|---|---|")
    for r in a.recipes:
        typer.echo(
            f"| {r.name} | {r.strategy} | {r.tp} | {r.fp} | {r.tn} | {r.fn} | "
            f"{r.precision} | {r.recall} | {r.f1} |"
        )
    if a.verifiers:
        typer.echo("")
        typer.echo("## Verifiers (M8)")
        typer.echo("")
        typer.echo("| verifier | lang | enabled | AUC | chosen_threshold | P | R | F1 |")
        typer.echo("|---|---|---|---|---|---|---|---|")
        for v in a.verifiers:
            typer.echo(
                f"| {v.verifier} | {v.language} | {v.enabled} | {v.auc} | "
                f"{v.chosen_threshold} | {v.chosen_precision} | "
                f"{v.chosen_recall} | {v.chosen_f1} |"
            )
    if a.notes:
        typer.echo("")
        typer.echo("## Notes")
        for n in a.notes:
            typer.echo(f"- {n}")


@app.command("diff")
def cmd_diff(  # pragma: no cover
    baseline: Path = typer.Option(..., "--baseline", help="committed baseline JSON"),
    new: Path = typer.Option(..., "--new", help="fresh artifact JSON to compare"),
) -> None:
    """Side-by-side delta between two artifacts (regression triage)."""
    a, _ = load(baseline)
    b, _ = load(new)

    def _changed(a_val: object, b_val: object) -> bool:
        return a_val != b_val

    def _emit(field: str, a_val: object, b_val: object) -> None:
        marker = " " if not _changed(a_val, b_val) else "*"
        typer.echo(f"  [{marker}] {field}: {a_val!r}  ->  {b_val!r}")

    typer.echo("# top-level")
    _emit("corpus_id", a.corpus_id, b.corpus_id)
    _emit("corpus_sha256", a.corpus_sha256[:12], b.corpus_sha256[:12])
    _emit("actor_count_total", a.actor_count_total, b.actor_count_total)
    _emit(
        "actor_count_simhash_qualifying",
        a.actor_count_simhash_qualifying,
        b.actor_count_simhash_qualifying,
    )
    _emit("label_counts", a.label_counts, b.label_counts)

    typer.echo("\n# simhash")
    a_sim = {(s.primitive, s.language): s for s in a.simhash}
    b_sim = {(s.primitive, s.language): s for s in b.simhash}
    for key in sorted(set(a_sim) | set(b_sim)):
        typer.echo(f"  {key}")
        sa = a_sim.get(key)
        sb = b_sim.get(key)
        if sa and sb:
            _emit("    enabled", sa.enabled, sb.enabled)
            _emit("    auc", sa.auc, sb.auc)
            _emit("    chosen_threshold", sa.chosen_threshold, sb.chosen_threshold)
            _emit("    chosen_f1", sa.chosen_f1, sb.chosen_f1)
        else:
            typer.echo(f"    ONLY IN {'baseline' if sa else 'new'}")

    typer.echo("\n# recipes")
    a_rec = {r.name: r for r in a.recipes}
    b_rec = {r.name: r for r in b.recipes}
    for name in sorted(set(a_rec) | set(b_rec)):
        typer.echo(f"  {name}")
        ra = a_rec.get(name)
        rb = b_rec.get(name)
        if ra and rb:
            _emit("    precision", ra.precision, rb.precision)
            _emit("    recall", ra.recall, rb.recall)
            _emit("    f1", ra.f1, rb.f1)
            _emit("    tp/fp/tn/fn", (ra.tp, ra.fp, ra.tn, ra.fn), (rb.tp, rb.fp, rb.tn, rb.fn))
        else:
            typer.echo(f"    ONLY IN {'baseline' if ra else 'new'}")


__all__ = ["app"]
