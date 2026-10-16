<script>
  import StatTile from '$lib/components/StatTile.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import { HEALTH, SYS_STATS } from '$lib/data.js';

  // ready = calm/neutral, degraded = accent, down = red.
  const toneFor = (s) => (s === 'down' ? 'critical' : s === 'degraded' ? 'high' : 'neutral');
  const anyDown = HEALTH.components.some((c) => c.status === 'down');
  const anyDegraded = HEALTH.components.some((c) => c.status === 'degraded');
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">System</span><span class="sep">/</span><span class="slug">health</span></div>
      <h1>System health</h1>
    </div>
    {#if anyDown}
      <Badge tone="critical" dot>Not ready</Badge>
    {:else if anyDegraded}
      <Badge tone="high" dot>Degraded</Badge>
    {:else}
      <Badge tone="neutral" dot>Ready</Badge>
    {/if}
  </div>

  <div class="body">
    <div class="tiles">
      {#each SYS_STATS as s}
        <StatTile {...s} />
      {/each}
    </div>

    <Panel title="Component readiness">
      {#each HEALTH.components as c}
        <div class="crow">
          <Badge tone={toneFor(c.status)} dot>{c.status}</Badge>
          <span class="name">{c.name}</span>
          <span class="detail">{c.detail}</span>
        </div>
      {/each}
    </Panel>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { flex: 0 0 auto; display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 16px 20px; border-bottom: 1px solid var(--border); }
  .crumb { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); }
  .group, .sep { color: var(--text-faint); }
  .group { text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .slug { color: var(--accent-text); }
  h1 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); }

  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(172px, 1fr)); gap: 12px; margin-bottom: 16px; }

  .crow {
    display: grid;
    grid-template-columns: 110px 160px 1fr;
    gap: 14px;
    align-items: center;
    padding: 9px 12px;
    border-bottom: 1px solid var(--border);
  }
  .crow:last-child { border-bottom: none; }
  .name { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .detail { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  @media (max-width: 640px) {
    .crow { grid-template-columns: 100px 1fr; }
    .crow .detail { grid-column: 2; }
  }
</style>
