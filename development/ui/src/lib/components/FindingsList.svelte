<script>
  import Badge from './Badge.svelte';
  import TierBadge from './TierBadge.svelte';
  // Renders the redacted `classification` payload (classification_audit_payload):
  // per-stage provenance floors, masked regex/presidio matches, review flags.
  let { classification } = $props();

  const c = $derived(classification ?? {});
  const flagTone = (k) => (k === 'llm_higher_tier' ? 'high' : 'neutral');
</script>

<div class="findings">
  <!-- Aggregation strip -->
  <div class="section">
    <div class="slabel">Aggregation (MAX floor, never lowered)</div>
    <div class="stages">
      {#each (c.provenance ?? []) as p}
        <div class="stage">
          <span class="sname">{p.stage}</span>
          <TierBadge tier={p.tier_floor} dot={false} />
          {#if p.fail_closed}<span class="fc">fail-closed</span>{/if}
        </div>
      {/each}
      <span class="eq">=</span>
      <div class="stage"><span class="sname">tier</span><TierBadge tier={c.tier} /></div>
    </div>
    <div class="versions">ruleset {c.ruleset_version ?? '?'} · pii {c.pii_map_version ?? '?'}{#if c.fail_closed} · fail-closed{/if}</div>
  </div>

  <!-- Review flags -->
  {#if c.review_flags?.length}
    <div class="section">
      <div class="slabel">Review flags</div>
      {#each c.review_flags as f}
        <div class="frow">
          <Badge tone={flagTone(f.kind)} dot>{f.kind}</Badge>
          <span class="fdetail">{f.detail}</span>
          {#if f.suggested_tier}<span class="fsug">suggests {f.suggested_tier}</span>{/if}
          {#if f.corroborated}<span class="fcorr">corroborated</span>{/if}
        </div>
      {/each}
    </div>
  {/if}

  <!-- Regex matches -->
  {#if c.regex_matches?.length}
    <div class="section">
      <div class="slabel">Regex markers ({c.regex_matches.length})</div>
      {#each c.regex_matches as m}
        <div class="mrow">
          <span class="mrule">{m.rule}</span>
          <TierBadge tier={m.tier_floor} dot={false} />
          <span class="mspan">[{m.start}:{m.end}] {m.lang}</span>
          <span class="mtext">{m.matched_text}</span>
        </div>
      {/each}
    </div>
  {/if}

  <!-- Presidio matches -->
  {#if c.presidio_matches?.length}
    <div class="section">
      <div class="slabel">PII entities ({c.presidio_matches.length})</div>
      {#each c.presidio_matches as m}
        <div class="mrow">
          <span class="mrule">{m.entity_type}</span>
          <TierBadge tier={m.tier_floor} dot={false} />
          <span class="mspan">[{m.start}:{m.end}] {m.language} · {m.score}</span>
          <span class="mtext">{m.matched_text}</span>
        </div>
      {/each}
    </div>
  {/if}

  <!-- LLM advisory (redacted: no summary/indicators) -->
  {#if c.llm}
    <div class="section">
      <div class="slabel">LLM advisory (flag-only, tier unchanged)</div>
      <div class="llm">suggests {c.llm.suggested_tier} · confidence {c.llm.confidence} · {c.llm.model} · attempts {c.llm.attempts}</div>
    </div>
  {/if}
</div>

<style>
  .findings { display: flex; flex-direction: column; }
  .section { padding: 10px 12px; border-bottom: 1px solid var(--border); }
  .section:last-child { border-bottom: none; }
  .slabel { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); margin-bottom: 8px; }

  .stages { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .stage { display: inline-flex; align-items: center; gap: 6px; }
  .sname { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-muted); }
  .fc { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--red-text); }
  .eq { font-family: var(--font-mono); color: var(--text-faint); }
  .versions { margin-top: 8px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .frow { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 4px 0; }
  .fdetail { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-secondary); }
  .fsug { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .fcorr { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--accent-text); }

  .mrow { display: grid; grid-template-columns: minmax(0,1.3fr) 96px minmax(0,1fr) minmax(0,1fr); gap: 10px; align-items: baseline; padding: 4px 0; }
  .mrule { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .mspan { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .mtext { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .llm { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-secondary); }
</style>
