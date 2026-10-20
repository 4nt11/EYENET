<script>
  import { onMount } from 'svelte';
  import { fetchMonitored, bySource } from '$lib/reader.js';

  // Reader landing: one square per source (any platform). Pick a source, then
  // drill into its monitored groups, then into a conversation. Reuses GET
  // /v1/groups (monitored subset) — no reader-specific list.
  let groups = $state([]);
  let error = $state(null);
  let loaded = $state(false);

  onMount(async () => {
    try {
      groups = await fetchMonitored();
    } catch (e) {
      error = e.message;
    }
    loaded = true;
  });

  const sources = $derived(bySource(groups));
</script>

<main>
  <div class="head">
    <div class="crumb"><span class="group">Investigate</span><span class="sep">/</span><span class="slug">reader</span></div>
    <h1>Reader</h1>
    <p class="desc">Reconstruct monitored conversations. Pick a source to see its monitored groups, then open a conversation.</p>
  </div>

  <div class="body">
    {#if !loaded}
      <p class="pnote">Loading…</p>
    {:else if error}
      <p class="pnote err">Could not load: {error}</p>
    {:else if !sources.length}
      <p class="pnote">Nothing monitored yet. Monitor a forum category or a chat in <a href="/monitored-groups">Monitored groups</a>.</p>
    {:else}
      <ul class="cards">
        {#each sources as s (s.id)}
          <li>
            <a class="card" href={`/reader/source/${s.id}`}>
              <span class="label">Source</span>
              <span class="name" title={s.name}>{s.name}</span>
              <span class="count">{s.items.length} {s.items.length === 1 ? 'group' : 'groups'}</span>
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { padding: 20px 24px 0; }
  .crumb { display: flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .crumb .sep { color: var(--text-faint); }
  h1 { margin: 4px 0 0; font-size: var(--fs-20); color: var(--text-body); }
  .desc { color: var(--text-secondary); font-size: var(--fs-13); max-width: 70ch; }
  .body { flex: 1; min-height: 0; overflow: auto; padding: 8px 24px 24px; }
  .cards { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; align-items: stretch; }
  .cards > li { display: flex; min-width: 0; }
  .card { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 16px; text-decoration: none; }
  .card:hover { border-color: var(--accent); }
  .label { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  /* brighter than --accent so the source pops; clamp to 2 lines */
  .name { color: #c88bff; font-family: var(--font-mono); font-size: var(--fs-16); word-break: break-all; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .count { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-secondary); }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote.err { color: var(--red-text); }
  a { color: var(--accent); }
</style>
