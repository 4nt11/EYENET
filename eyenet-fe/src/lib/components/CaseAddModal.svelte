<script>
  // Modal: add a reader post to a case. The operator picks a target (new case or an
  // existing open one) and a scope (just this post, or the whole author). Cases track
  // actors, so "this post" also seeds the post's author; "this author" opens a case on
  // them and materializes their on-disk post history (server-side).
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api.js';

  // post: { id (message_id), actor_id, author, threadTitle }
  let { post, onClose } = $props();

  let cases = $state([]);
  let target = $state('new'); // 'new' | 'existing'
  let title = $state('');
  let existingId = $state('');
  let scope = $state('post'); // 'post' | 'author'
  let busy = $state(false);
  let err = $state(null);

  onMount(async () => {
    title = (post.threadTitle || `Case: ${post.author || 'actor'}`).slice(0, 256);
    try {
      const p = await apiGet('/v1/cases?limit=200', { auth: true });
      const rows = p.items ?? p ?? [];
      cases = rows.filter((c) => c.state === 'open');
      if (cases.length) existingId = cases[0].case_id;
    } catch (e) {
      // Non-fatal: operator can still create a new case.
      cases = [];
    }
  });

  async function confirm() {
    err = null;
    if (target === 'new' && title.trim().length < 4) {
      err = 'Title needs at least 4 characters.';
      return;
    }
    if (target === 'existing' && !existingId) {
      err = 'Pick a case.';
      return;
    }
    busy = true;
    try {
      let caseId = existingId;
      if (target === 'new') {
        const c = await apiPost('/v1/cases', { title: title.trim(), description: null }, { auth: true });
        caseId = c.case_id;
      }
      if (scope === 'author') {
        await apiPost(
          `/v1/cases/${caseId}/members/by-actor`,
          { actor_id: post.actor_id, include_posts: true, add_reason: 'Opened from reader on this author' },
          { auth: true }
        );
      } else {
        await apiPost(
          `/v1/cases/${caseId}/members/bulk`,
          {
            subjects: [
              { subject_kind: 'message', subject_id: post.id },
              { subject_kind: 'actor', subject_id: post.actor_id }
            ],
            add_reason: 'Added this post (and its author) from the reader'
          },
          { auth: true }
        );
      }
      onClose(true);
    } catch (e) {
      err = e.message ?? String(e);
    } finally {
      busy = false;
    }
  }
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && !busy && onClose(false)} />

<!-- svelte-ignore a11y_click_events_have_key_events -->
<div class="backdrop" onclick={() => onClose(false)} role="presentation">
  <div class="modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Add to case">
    <h2>Add to case</h2>
    <p class="ctx">{post.threadTitle || post.author || 'post'}</p>

    <div class="field">
      <span class="flabel">Case</span>
      <div class="seg">
        <button class="chip" class:on={target === 'new'} onclick={() => (target = 'new')}>New case</button>
        <button class="chip" class:on={target === 'existing'} onclick={() => (target = 'existing')} disabled={!cases.length}>Existing{#if !cases.length} (none open){/if}</button>
      </div>
    </div>

    {#if target === 'new'}
      <div class="field">
        <span class="flabel">Title</span>
        <input class="fin" bind:value={title} maxlength="256" placeholder="Case title" />
      </div>
    {:else}
      <div class="field">
        <span class="flabel">Pick case</span>
        <select class="fin" bind:value={existingId}>
          {#each cases as c}<option value={c.case_id}>{c.title}</option>{/each}
        </select>
      </div>
    {/if}

    <div class="field">
      <span class="flabel">Scope</span>
      <div class="seg">
        <button class="chip" class:on={scope === 'post'} onclick={() => (scope = 'post')}>This post</button>
        <button class="chip" class:on={scope === 'author'} onclick={() => (scope = 'author')}>All posts by {post.author || 'author'}</button>
      </div>
      <p class="hint">
        {#if scope === 'post'}Adds this post and its author to the case.
        {:else}Adds {post.author || 'the author'} and every post we hold by them (in tracked categories).{/if}
      </p>
    </div>

    {#if err}<p class="err">{err}</p>{/if}

    <div class="actions">
      <button class="btn ghost" onclick={() => onClose(false)} disabled={busy}>Cancel</button>
      <button class="btn" onclick={confirm} disabled={busy}>{busy ? 'Adding…' : 'Add to case'}</button>
    </div>
  </div>
</div>

<style>
  .backdrop { position: fixed; inset: 0; z-index: 100; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; padding: 24px; }
  .modal { width: 100%; max-width: 460px; background: var(--panel); border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow-2, 0 8px 24px rgba(0,0,0,0.5)); }
  h2 { margin: 0 0 2px; font-size: var(--fs-16); color: var(--text-body); }
  .ctx { margin: 0 0 16px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .field { margin-bottom: 14px; display: flex; flex-direction: column; gap: 6px; }
  .flabel { font-family: var(--font-sans); font-size: var(--fs-10); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .seg { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip { appearance: none; padding: 5px 11px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); cursor: pointer; }
  .chip:hover:not(:disabled) { background: var(--panel-2); }
  .chip:disabled { opacity: .45; cursor: not-allowed; }
  .chip.on { background: var(--accent-fill); border-color: var(--accent); color: var(--text); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .hint { margin: 0; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .err { margin: 0 0 10px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--red-text); }
  .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
  .btn { appearance: none; padding: 7px 14px; border: 1px solid var(--accent); border-radius: var(--radius); background: var(--accent-fill); color: var(--text); font-family: var(--font-mono); font-size: var(--fs-12); cursor: pointer; }
  .btn:hover:not(:disabled) { background: var(--accent); }
  .btn.ghost { background: transparent; border-color: var(--border-strong); color: var(--text-secondary); }
  .btn:disabled { opacity: .5; cursor: not-allowed; }
</style>
