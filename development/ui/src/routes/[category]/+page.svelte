<script>
  import { page } from '$app/stores';
  import { BY_SLUG } from '$lib/nav.js';

  let item = $derived(BY_SLUG[$page.params.category]);
</script>

<main>
  {#if item}
    <div class="head">
      <div class="crumb">
        <span class="group">{item.group}</span>
        <span class="sep">/</span>
        <span class="slug">{item.slug}</span>
      </div>
      <h1>{item.label}</h1>
      <p class="desc">{item.desc}</p>
    </div>

    <div class="stub-body">
      <div class="stub-card">
        {#if item.future}
          <span class="tag future">○ Planned</span>
          <p>No API surface yet. This section needs new routes · a <code>{item.slug}</code> tag plus its endpoints · before it can be wired.</p>
        {:else}
          <span class="tag pending">· Screen not built</span>
          <p>The <code>/v1/{item.slug}</code> API exists and is implemented. This mock screen hasn't been laid out yet.</p>
        {/if}
      </div>
    </div>
  {:else}
    <div class="head">
      <h1>Unknown section</h1>
      <p class="desc">No category matches <code>{$page.params.category}</code>.</p>
    </div>
  {/if}
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: auto; background: var(--black); }
  .head { flex: 0 0 auto; padding: 20px; border-bottom: 1px solid var(--border); }
  .crumb { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); }
  .group { color: var(--text-faint); text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .sep { color: var(--text-faint); }
  .slug { color: var(--accent-text); }
  h1 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); }
  .desc { margin: 6px 0 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); max-width: 60ch; }

  .stub-body { flex: 1; display: flex; align-items: flex-start; padding: 20px; }
  .stub-card { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 16px 18px; max-width: 60ch; display: flex; flex-direction: column; gap: 10px; }
  .tag { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; }
  .tag.future { color: var(--text-faint); }
  .tag.pending { color: var(--accent-text); }
  .stub-card p { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-secondary); line-height: var(--lh-normal); }
  code { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); background: var(--surface); padding: 1px 5px; border-radius: var(--radius-sm); }
</style>
