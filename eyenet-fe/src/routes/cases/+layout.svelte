<script>
  import { page } from '$app/stores';
  import { caseCtx } from '$lib/case.svelte.js';
  let { children } = $props();

  // The Overview (/cases) is the case picker and is never gated. Every deeper
  // Cases sub-view requires an active case (tenant-style scoping).
  const isSub = $derived($page.url.pathname !== '/cases');
  const gated = $derived(isSub && !caseCtx.active);
</script>

{#if gated}
  <main class="gate">
    <div class="inner">
      <div class="mode">Case mode</div>
      <h1>No case selected</h1>
      <p>This view scopes to a single case. Enter one from the switcher in the top bar, or the caseload.</p>
      <a class="link" href="/cases">Go to caseload</a>
    </div>
  </main>
{:else}
  {@render children()}
{/if}

<style>
  .gate { flex: 1; min-width: 0; display: flex; align-items: center; justify-content: center; padding: 40px; background: var(--black); }
  .inner { max-width: 60ch; text-align: center; }
  .mode { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--accent-text); margin-bottom: 8px; }
  h1 { margin: 0 0 8px; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); }
  p { margin: 0 0 14px; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); line-height: var(--lh-normal); }
  .link { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent-text); text-decoration: none; }
  .link:hover { text-decoration: underline; }
</style>
