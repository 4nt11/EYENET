<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { fetchMonitored, kindLabel, groupHref, sourceName } from '$lib/reader.js';

  // One source's monitored groups. Narrowed at the API by source_id. Cards open
  // into a conversation (forum category -> threads, chat/channel -> messages).
  const sourceId = $page.params.id;
  let groups = $state([]);
  let error = $state(null);
  let loaded = $state(false);

  onMount(async () => {
    try {
      const all = await fetchMonitored(sourceId);
      all.sort((a, b) =>
        (a.title || a.platform_groupid).localeCompare(b.title || b.platform_groupid)
      );
      groups = all;
    } catch (e) {
      error = e.message;
    }
    loaded = true;
  });

  const name = $derived(groups.length ? sourceName(groups[0]) : sourceId);
</script>

<main>
  <div class="head">
    <div class="crumb">
      <span class="group">Investigate</span><span class="sep">/</span>
      <a class="slug" href="/reader">reader</a><span class="sep">/</span>
      <span class="slug" title={name}>{name}</span>
    </div>
    <h1 title={name}>{name}</h1>
    <p class="desc">Monitored groups on this source. Forum categories open to their threads; chats and channels open to their messages.</p>
  </div>

  <div class="body">
    {#if !loaded}
      <p class="pnote">Loading…</p>
    {:else if error}
      <p class="pnote err">Could not load: {error}</p>
    {:else if !groups.length}
      <p class="pnote">Nothing monitored on this source. <a href="/reader">Back to sources.</a></p>
    {:else}
      <ul class="cards">
        {#each groups as g (g.group_id)}
          <li>
            <a class="card" href={groupHref(g)}>
              <span class="kind">{kindLabel(g.kind)}</span>
              <span class="title">{g.title || g.platform_groupid}</span>
              <span class="pid">{g.platform_groupid}</span>
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
  .crumb a.slug { color: var(--text-faint); text-decoration: none; }
  .crumb a.slug:hover { color: var(--accent); }
  h1 { margin: 4px 0 0; font-size: var(--fs-20); color: var(--text-body); word-break: break-all; }
  .desc { color: var(--text-secondary); font-size: var(--fs-13); max-width: 70ch; }
  .body { flex: 1; min-height: 0; overflow: auto; padding: 8px 24px 24px; }
  .cards { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; align-items: stretch; }
  .cards > li { display: flex; min-width: 0; }
  .card { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 14px; text-decoration: none; }
  .card:hover { border-color: var(--accent); }
  .kind { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--accent); }
  .title { color: var(--text-body); font-size: var(--fs-14); word-break: break-word; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .pid { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); word-break: break-all; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote.err { color: var(--red-text); }
  a { color: var(--accent); }
</style>
