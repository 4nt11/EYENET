<script>
  import StatTile from '$lib/components/StatTile.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import { fmtGiB } from '$lib/api.js';

  let { data } = $props();

  // /v1/readyz surfaces exactly these three flags (ReadyComponents schema).
  const COMPONENT_ORDER = ['storage', 'bus', 'auth_keys'];

  // up = purple, down = red. (No middle "degraded" per-component: the contract
  // is up/down; "degraded" is the overall roll-up only.)
  const toneFor = (s) => (s === 'down' ? 'critical' : 'high');

  let components = $derived(
    data.ready
      ? COMPONENT_ORDER.map((k) => ({ name: k, status: data.ready.components[k] }))
      : []
  );

  let overall = $derived(
    !data.ready
      ? { tone: 'critical', label: 'Unavailable' }
      : data.ready.status === 'degraded'
        ? { tone: 'warn', label: 'Degraded' }
        : { tone: 'high', label: 'Ready' }
  );

  // Largest two meaningful units, so it's unambiguous at every scale and
  // visibly ticks on a fresh server: "42s", "2m 5s", "6h 12m", "14d 6h".
  const fmtUptime = (secs) => {
    const s = Math.floor(secs);
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s % 60}s`;
    return `${s}s`;
  };

  // Real host stats from /v1/system (uptime / CPU / RAM / disk / load). Only these exist.
  let tiles = $derived(
    data.system
      ? [
          { label: 'Uptime', value: fmtUptime(data.system.uptime_seconds) },
          { label: 'CPU', value: data.system.cpu_percent.toFixed(0), unit: '%' },
          {
            label: 'Memory',
            value: data.system.mem.percent.toFixed(0),
            unit: '%',
            sub: `${fmtGiB(data.system.mem.used)} / ${fmtGiB(data.system.mem.total)}`
          },
          {
            label: 'Disk (data)',
            value: ((data.system.disk.data.used / data.system.disk.data.total) * 100).toFixed(0),
            unit: '%',
            sub: `${fmtGiB(data.system.disk.data.free)} free`
          },
          { label: 'Load (1m)', value: data.system.load1.toFixed(2) },
          { label: 'Version', value: data.system.version }
        ]
      : []
  );

  // /v1/system needs read:metrics. 401/403 = no token yet (expected), not an error.
  const NOAUTH = new Set([401, 403]);
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">System</span><span class="sep">/</span><span class="slug">health</span></div>
      <h1>System health</h1>
    </div>
    <Badge tone={overall.tone} dot>{overall.label}</Badge>
  </div>

  <div class="body">
    {#if data.system}
      <div class="tiles">
        {#each tiles as s}
          <StatTile {...s} />
        {/each}
      </div>
    {:else if NOAUTH.has(data.systemStatus)}
      <p class="note">Host stats need a token with <code>read:metrics</code>. Sign in to view CPU · memory · disk · load.</p>
    {:else}
      <p class="note">Host stats unavailable (<code>/v1/system</code> did not respond).</p>
    {/if}

    <Panel title="Component readiness">
      {#if data.ready}
        {#each components as c}
          <div class="crow">
            <Badge tone={toneFor(c.status)} dot>{c.status}</Badge>
            <span class="name">{c.name}</span>
            <span class="detail">{data.system?.components?.[c.name] ?? ''}</span>
          </div>
        {/each}
      {:else}
        <p class="note">Readiness probe unreachable: {data.readyError}</p>
      {/if}
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

  .note { margin: 0 0 16px; padding: 12px; border: 1px solid var(--border); font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .note code { color: var(--accent-text); }

  .crow {
    display: grid;
    grid-template-columns: 110px 130px 1fr;
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
