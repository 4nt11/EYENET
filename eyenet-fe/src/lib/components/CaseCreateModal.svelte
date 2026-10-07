<script>
  import { tick } from 'svelte';
  import Button from './Button.svelte';

  // Create a new case, seeded with some actors. `seedCount` is shown so the operator
  // knows how many actors get added on create. onConfirm(title, description).
  let {
    seedCount = 0,
    seedLabel = 'actor(s)',
    defaultTitle = '',
    defaultDescription = '',
    busy = false,
    error = null,
    onConfirm,
    onCancel
  } = $props();

  let title = $state(defaultTitle);
  let description = $state(defaultDescription);
  let titleEl;

  $effect(() => {
    tick().then(() => titleEl?.focus());
  });

  let canSubmit = $derived(title.trim().length >= 4 && !busy);
  function submit() {
    if (canSubmit) onConfirm(title.trim(), description.trim());
  }
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onCancel()} />

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="scrim" role="presentation" onclick={onCancel}>
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions -->
  <div class="modal" role="dialog" tabindex="-1" aria-modal="true" aria-label="Create case" onclick={(e) => e.stopPropagation()}>
    <div class="mhead">
      <span class="mtitle">New case</span>
      <button class="mclose" onclick={onCancel} aria-label="Cancel">×</button>
    </div>
    <div class="mbody">
      <p class="mhint">Seeds the case with <b>{seedCount}</b> {seedLabel} (audited).</p>
      <label class="fld">
        <span class="flk">Title <span class="req">required</span></span>
        <input class="txt" bind:this={titleEl} bind:value={title} placeholder="e.g. SoulhemTeam / SQX reseller cluster" spellcheck="false" />
        {#if title.trim().length > 0 && title.trim().length < 4}
          <span class="warn">needs at least 4 characters</span>
        {/if}
      </label>
      <label class="fld">
        <span class="flk">Description</span>
        <textarea class="txt area" bind:value={description} rows="3" placeholder="Optional context / origin query"></textarea>
      </label>
      {#if error}<p class="err">{error}</p>{/if}
    </div>
    <div class="mfoot">
      <Button variant="ghost" size="sm" onclick={onCancel}>Cancel</Button>
      <Button variant="primary" size="sm" disabled={!canSubmit} onclick={submit}>
        {busy ? 'Creating…' : 'Create + add'}
      </Button>
    </div>
  </div>
</div>

<style>
  .scrim { position: fixed; inset: 0; z-index: 100; display: flex; align-items: center; justify-content: center; background: rgba(0, 0, 0, 0.6); padding: 20px; }
  .modal { width: 100%; max-width: 460px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: 0 16px 48px rgba(0, 0, 0, 0.6); display: flex; flex-direction: column; }
  .mhead { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 14px; border-bottom: 1px solid var(--border); }
  .mtitle { font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text); }
  .mclose { appearance: none; background: transparent; border: none; color: var(--text-faint); font-size: var(--fs-18); line-height: 1; cursor: pointer; padding: 0 4px; }
  .mclose:hover { color: var(--accent-text); }
  .mbody { padding: 14px; display: flex; flex-direction: column; gap: 12px; }
  .mhint { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); }
  .fld { display: flex; flex-direction: column; gap: 5px; }
  .flk { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .req { color: var(--accent-text); }
  .txt { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 9px; }
  .txt:focus { outline: none; border-color: var(--accent); }
  .area { font-family: var(--font-sans); resize: vertical; min-height: 56px; }
  .warn { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--warn-text); }
  .err { margin: 0; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--red-text); }
  .mfoot { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 14px; border-top: 1px solid var(--border); }
</style>
