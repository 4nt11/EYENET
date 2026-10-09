<script>
  import Badge from './Badge.svelte';
  // Activity-rhythm readout: the circadian.* UTC histograms + EYENET's timezone
  // inference. A tz is a HINT (zone_best only when a second signal agrees), never
  // asserted fact — mirrors the backend honesty contract.
  let { circadian } = $props();

  const tz = $derived(circadian?.inferred_tz ?? {});
  const hours = $derived(circadian?.hour_histogram ?? []);
  const dows = $derived(circadian?.dow_histogram ?? []);
  const DOW = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

  const hourMax = $derived(Math.max(0, ...hours));
  const dowMax = $derived(Math.max(0, ...dows));
  const barH = (v, max) => (max > 0 ? Math.round((v / max) * 100) : 0);

  const offLabel = (o) => (o == null ? '—' : `UTC${o >= 0 ? '+' : ''}${o}`);
  const hh = (h) => (h == null ? '—' : `${String(h).padStart(2, '0')}:00`);
  const win = (w) => (w ? `${hh(w[0])} – ${hh(w[1])}` : '—');
  const confTone = (c) => ({ high: 'high', medium: 'medium', low: 'low' })[c] ?? 'neutral';

  const zoneLine = $derived(
    tz.zone_best
      ? tz.zone_best
      : (tz.zone_candidates?.length ? tz.zone_candidates.join(' / ') : 'unknown')
  );
</script>

<div class="circ">
  <div class="bar">
    <span class="title">Activity rhythm</span>
    <Badge tone={confTone(tz.confidence)} dot>{tz.confidence ?? 'none'}</Badge>
  </div>

  <div class="tz">
    <div class="zone">
      <span class="zname">{zoneLine}</span>
      <span class="zoff">{offLabel(tz.offset_hours)}</span>
    </div>
    {#if tz.supporting_signals?.length}
      <div class="sigs">
        {#each tz.supporting_signals as s}<span class="sig">{s}</span>{/each}
      </div>
    {/if}
  </div>

  <div class="rows">
    <div class="r"><span class="k">Active (local)</span><span class="v">{win(tz.local_active_window)}</span></div>
    <div class="r"><span class="k">Sleep gap (UTC)</span><span class="v">{win(circadian?.quiet_span_utc ?? tz.quiet_window_utc)}</span></div>
  </div>

  <!-- Hour-of-day (UTC) -->
  <div class="section-label">Hours (UTC)</div>
  <div class="spark" role="img" aria-label="activity by UTC hour">
    {#each hours as v, i}
      <span
        class="hbar"
        class:peak={hourMax > 0 && v === hourMax}
        style="height:{Math.max(barH(v, hourMax), 2)}%"
        title="{String(i).padStart(2, '0')}:00 — {(v * 100).toFixed(1)}%"
      ></span>
    {/each}
  </div>
  <div class="axis"><span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>

  <!-- Day-of-week -->
  <div class="section-label">Week</div>
  <div class="week">
    {#each dows as v, i}
      <div class="dcol" title="{(v * 100).toFixed(1)}%">
        <span class="dbar" style="height:{Math.max(barH(v, dowMax), 2)}%"></span>
        <span class="dlabel">{DOW[i]}</span>
      </div>
    {/each}
  </div>
</div>

<style>
  .circ {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--panel);
    padding: 12px 14px;
    font-family: var(--font-sans);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .bar { display: flex; align-items: center; justify-content: space-between; }
  .title {
    font-size: var(--fs-12);
    font-weight: var(--fw-semibold);
    letter-spacing: var(--tracking-label);
    text-transform: uppercase;
    color: var(--text-secondary);
  }
  .tz { display: flex; flex-direction: column; gap: 6px; }
  .zone { display: flex; align-items: baseline; gap: 10px; }
  .zname { font-size: 16px; font-weight: var(--fw-semibold); color: var(--text-body); }
  .zoff {
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    color: var(--text-muted);
    letter-spacing: var(--tracking-data);
  }
  .sigs { display: flex; flex-wrap: wrap; gap: 4px; }
  .sig {
    font-family: var(--font-mono);
    font-size: var(--fs-11);
    color: var(--text-faint);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 1px 5px;
  }
  .rows { display: flex; flex-direction: column; gap: 3px; }
  .r { display: flex; justify-content: space-between; font-size: var(--fs-12); }
  .k { color: var(--text-muted); }
  .v { font-family: var(--font-mono); color: var(--text-body); letter-spacing: var(--tracking-data); }
  .section-label {
    font-size: var(--fs-11);
    letter-spacing: var(--tracking-label);
    text-transform: uppercase;
    color: var(--text-faint);
    margin-top: 2px;
  }
  .spark { display: flex; align-items: flex-end; gap: 1px; height: 44px; }
  .hbar { flex: 1; background: var(--border-strong, var(--border)); border-radius: 1px 1px 0 0; min-height: 1px; }
  .hbar.peak { background: var(--accent); }
  .axis {
    display: flex; justify-content: space-between;
    font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint);
  }
  .week { display: flex; gap: 4px; height: 40px; align-items: flex-end; }
  .dcol { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px; height: 100%; justify-content: flex-end; }
  .dbar { width: 100%; background: var(--accent); opacity: 0.75; border-radius: 1px 1px 0 0; min-height: 1px; }
  .dlabel { font-size: var(--fs-11); color: var(--text-faint); font-family: var(--font-mono); }
</style>
