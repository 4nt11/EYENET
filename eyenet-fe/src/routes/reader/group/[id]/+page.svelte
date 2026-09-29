<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import DOMPurify from 'dompurify';
  import { apiGet, apiPost } from '$lib/api.js';

  // Message view for any group: a forum thread OR a chat/channel/room. Posts
  // render their evidence-faithful body_html (SANITIZED — this is threat-actor
  // HTML; raw {@html} would XSS the console); chat messages with no html fall
  // back to escaped body text. If any post is [hide]-gated, the operator can
  // enqueue a reply-to-unlock (posted by the collector under throttle).
  let msgs = $state([]);
  let error = $state(null);
  let loaded = $state(false);
  let replyText = $state('');
  let replyMsg = $state(null);
  let submitting = $state(false);

  const gated = $derived(msgs.some((m) => m.reply_gated));

  onMount(load);

  async function load() {
    loaded = false;
    try {
      const p = await apiGet(`/v1/groups/${$page.params.id}/messages?limit=500`, { auth: true });
      msgs = p.items ?? [];
    } catch (e) {
      error = e.message;
    }
    loaded = true;
  }

  const clean = (html) => DOMPurify.sanitize(html ?? '');
  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : '');

  async function reply() {
    const message = replyText.trim();
    if (!message) return;
    submitting = true;
    replyMsg = null;
    try {
      await apiPost(`/v1/groups/${$page.params.id}/reply`, { message }, { auth: true });
      replyMsg = 'Queued. The collector posts it under throttle, then re-fetches to unlock.';
      replyText = '';
    } catch (e) {
      replyMsg = 'Failed: ' + e.message;
    }
    submitting = false;
  }
</script>

<main>
  <div class="head">
    <div class="crumb">
      <a class="slug-link" href="/reader">reader</a><span class="sep">/</span><span class="slug">messages</span>
    </div>
    <h1>Conversation</h1>
    {#if gated}<span class="gatehint">Contains [hide]-gated posts · reply below to unlock.</span>{/if}
  </div>

  <div class="body">
    {#if !loaded}
      <p class="pnote">Loading…</p>
    {:else if error}
      <p class="pnote err">Could not load: {error}</p>
    {:else if !msgs.length}
      <p class="pnote">No posts stored yet.</p>
    {:else}
      <ol class="posts">
        {#each msgs as m}
          <li class="post" class:gatedpost={m.reply_gated}>
            <div class="pmeta">
              <span class="author">{m.author_display || m.author_username || 'unknown'}</span>
              <span class="ts">{fmt(m.ts)}</span>
              {#if m.reply_gated}<span class="badge">gated</span>{/if}
              {#if m.edited}<span class="badge edited">edited</span>{/if}
            </div>
            {#if m.body_html}
              <div class="pbody">{@html clean(m.body_html)}</div>
            {:else}
              <div class="pbody plain">{m.body}</div>
            {/if}
          </li>
        {/each}
      </ol>

      {#if gated}
        <div class="replybox">
          <div class="rlabel">Reply to unlock (posted by the collector, throttled — type like a lazy human)</div>
          <textarea class="fin" rows="2" bind:value={replyText} placeholder="thanks, appreciated"></textarea>
          <div class="ractions">
            <button class="btn" disabled={submitting || !replyText.trim()} onclick={reply}>Queue reply</button>
            {#if replyMsg}<span class="hint">{replyMsg}</span>{/if}
          </div>
        </div>
      {/if}
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { padding: 20px 24px 0; }
  .crumb { display: flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .slug-link { color: var(--text-secondary); text-decoration: none; }
  .slug-link:hover { color: var(--accent); }
  h1 { margin: 4px 0 0; font-size: var(--fs-20); color: var(--text-body); }
  .gatehint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--accent); }
  .body { flex: 1; min-height: 0; overflow: auto; padding: 12px 24px 24px; }
  .posts { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  .post { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; }
  .post.gatedpost { border-color: var(--accent); }
  .pmeta { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .author { color: var(--text-body); font-size: var(--fs-13); font-weight: 600; }
  .ts { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .badge { font-family: var(--font-sans); font-size: var(--fs-10); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--accent); border: 1px solid var(--accent); border-radius: 3px; padding: 0 5px; }
  .badge.edited { color: var(--text-faint); border-color: var(--border-strong); }
  .pbody { color: var(--text-body); font-size: var(--fs-13); line-height: 1.5; word-break: break-word; overflow-wrap: anywhere; }
  .pbody.plain { white-space: pre-wrap; font-family: var(--font-mono); font-size: var(--fs-12); }
  .replybox { margin-top: 14px; display: flex; flex-direction: column; gap: 6px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 14px; }
  .rlabel { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; resize: vertical; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .ractions { display: flex; align-items: center; gap: 10px; }
  .btn { background: var(--accent); color: var(--black); border: none; border-radius: var(--radius); font-family: var(--font-sans); font-size: var(--fs-12); padding: 6px 12px; cursor: pointer; }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote.err { color: var(--red-text); }
</style>
