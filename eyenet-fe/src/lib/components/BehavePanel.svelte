<script>
  import Badge from './Badge.svelte';
  // BEHAVE engine readout: lexicometry + stylometry primitives, the four simhash
  // comparators (per-language status), and the Verifier (NCD + GI) composite.
  let { behave } = $props();

  const pct = (v) => (v == null ? 0 : Math.round(v * 100));
  const stateTone = (s) => (s === 'SUSPECTED' ? 'high' : s === 'CONFIRMED' ? 'neutral' : s === 'skipped' ? 'low' : 'neutral');
</script>

<div class="behave">
  <div class="bar">
    <span class="title">BEHAVE analysis</span>
    <div class="tags">
      <Badge tone="neutral" dot>lang {behave.language}</Badge>
      <span class="meta">anchors {behave.anchors}</span>
      <span class="meta">{behave.dialect_region}</span>
    </div>
  </div>

  <!-- Activity (meta.*) -->
  {#if behave.activity}
    <div class="section">
      <div class="section-label">Activity (meta)</div>
      {#each behave.activity as p}
        <div class="prow">
          <span class="pname">{p.primitive}</span>
          <span class="plabel">{p.label}</span>
          <span class="pval">{p.value}</span>
          <span class="pkind">{p.kind}</span>
        </div>
      {/each}
    </div>
  {/if}

  <!-- Lexicometry + stylometry primitives -->
  <div class="section">
    <div class="section-label">Lexicometry</div>
    {#each behave.lexical as p}
      <div class="prow">
        <span class="pname">{p.primitive}</span>
        <span class="plabel">{p.label}</span>
        <span class="pval">{p.value}</span>
        <span class="pkind">{p.kind}</span>
      </div>
    {/each}
  </div>

  <div class="section">
    <div class="section-label">Stylometry</div>
    {#each behave.stylometric as p}
      <div class="prow">
        <span class="pname">{p.primitive}</span>
        <span class="plabel">{p.label}</span>
        <span class="pval">{p.value}</span>
        <span class="pkind">{p.kind}</span>
      </div>
    {/each}
  </div>

  <!-- The four simhash comparators -->
  <div class="section">
    <div class="section-label">Simhash comparators (Hamming)</div>
    {#each behave.comparators as c}
      <div class="crow">
        <span class="cname">{c.name}</span>
        {#if c.status === 'disabled'}
          <span class="cstate disabled">disabled</span>
          <span class="creason">{c.reason}</span>
        {:else if c.distance == null}
          <span class="cstate faint">no result</span>
          <span class="creason">{c.reason}</span>
        {:else}
          <span class="cstate" class:match={c.match} class:nomatch={!c.match}>{c.match ? 'match' : 'no match'}</span>
          <span class="creason">hamming {c.distance} {c.match ? '≤' : '>'} {c.threshold}</span>
        {/if}
      </div>
    {/each}
  </div>

  <!-- Verifier -->
  <div class="section">
    <div class="section-label">Verifier
      <Badge tone={stateTone(behave.verifier.state)} dot>{behave.verifier.state}</Badge>
    </div>

    {#if behave.verifier.composite != null}
      <div class="composite">
        <div class="meter">
          <div class="fill" style="width:{pct(behave.verifier.composite)}%"></div>
          <div class="floor" style="left:{pct(behave.verifier.floor)}%" title="composite floor {behave.verifier.floor}"></div>
        </div>
        <span class="cval">composite {behave.verifier.composite.toFixed(2)} · floor {behave.verifier.floor.toFixed(2)}</span>
      </div>
    {:else}
      <div class="skipped-note">Verifier skipped · corpus below minimum.</div>
    {/if}

    {#each behave.verifier.results as r}
      <div class="vrow" class:skipped={r.skipped}>
        <span class="vname">{r.verifier === 'compression_distance' ? 'NCD · compression_distance' : r.verifier === 'general_impostors' ? 'GI · general_impostors' : r.verifier}</span>
        <span class="vscore">{r.skipped ? 'skipped' : `score ${r.score.toFixed(2)}`}</span>
        <span class="vconf">conf {r.confidence.toFixed(1)}</span>
        <span class="vdetail">{r.detail}</span>
      </div>
    {/each}
  </div>
</div>

<style>
  .behave { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); overflow: hidden; }
  .bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 12px; background: var(--surface); border-bottom: 1px solid var(--border); flex-wrap: wrap; }
  .title { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--accent-text); }
  .tags { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .meta { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .section { padding: 10px 12px; border-bottom: 1px solid var(--border); }
  .section:last-child { border-bottom: none; }
  .section-label { display: flex; align-items: center; gap: 8px; font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); margin-bottom: 8px; }

  .prow { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1.3fr) 90px 90px; gap: 10px; align-items: baseline; padding: 3px 0; }
  .pname { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--accent-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .plabel { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-secondary); }
  .pval { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-body); text-align: right; }
  .pkind { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); text-align: right; }

  .crow { display: grid; grid-template-columns: minmax(0, 1.6fr) 90px 1fr; gap: 10px; align-items: baseline; padding: 3px 0; }
  .cname { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-body); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cstate { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; }
  .cstate.match { color: var(--accent-text); }
  .cstate.nomatch { color: var(--text-muted); }
  .cstate.disabled { color: var(--text-faint); }
  .cstate.faint { color: var(--text-faint); }
  .creason { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .composite { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
  .meter { position: relative; flex: 1; height: 6px; background: var(--surface); border: 1px solid var(--border); border-radius: 3px; overflow: hidden; }
  .fill { height: 100%; background: var(--accent); }
  .floor { position: absolute; top: -2px; width: 1px; height: 10px; background: var(--red-text); }
  .cval { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-body); white-space: nowrap; }
  .skipped-note { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); margin-bottom: 8px; }

  .vrow { display: grid; grid-template-columns: minmax(0, 1.4fr) 100px 80px 1fr; gap: 10px; align-items: baseline; padding: 3px 0; }
  .vrow.skipped { opacity: .55; }
  .vname { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .vscore { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); }
  .vrow.skipped .vscore { color: var(--text-faint); }
  .vconf { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .vdetail { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
</style>
