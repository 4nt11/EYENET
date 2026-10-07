<script>
  import { tick } from 'svelte';
  import Button from './Button.svelte';

  // Generic "confirm with an audited reason" modal (persona merge/split, add-to-case).
  // Preset reasons for one-click + a Custom… free-text box. `minLen` enforces the
  // server's minimum (e.g. case add_reason needs >=16). onConfirm(reason) / onCancel.
  let {
    title = 'Confirm',
    hint = '',
    presets = [],
    minLen = 3,
    confirmLabel = 'Confirm',
    destructive = false,
    busy = false,
    error = null,
    onConfirm,
    onCancel
  } = $props();

  let reason = $state('');
  let custom = $state(false);
  let reasonEl;

  function pick(r) {
    custom = false;
    reason = r;
  }
  async function enableCustom() {
    custom = true;
    reason = '';
    await tick();
    reasonEl?.focus();
  }

  let canSubmit = $derived(reason.trim().length >= minLen && !busy);
  function submit() {
    if (canSubmit) onConfirm(reason.trim());
  }
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onCancel()} />

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="scrim" role="presentation" onclick={onCancel}>
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions -->
  <div class="modal" role="dialog" tabindex="-1" aria-modal="true" aria-label={title} onclick={(e) => e.stopPropagation()}>
    <div class="mhead">
      <span class="mtitle">{title}</span>
      <button class="mclose" onclick={onCancel} aria-label="Cancel">×</button>
    </div>
    <div class="mbody">
      {#if hint}<p class="mhint">{hint}</p>{/if}
      <div class="fld">
        <span class="flk">Reason <span class="req">required</span></span>
        <div class="reasons">
          {#each presets as r}
            <button type="button" class="rchip" class:active={!custom && reason === r} onclick={() => pick(r)}>{r}</button>
          {/each}
          <button type="button" class="rchip cust" class:active={custom} onclick={enableCustom}>Custom…</button>
        </div>
        {#if custom}
          <textarea class="txt" bind:this={reasonEl} bind:value={reason} rows="2" placeholder={`Reason (audited, min ${minLen} chars)`}></textarea>
        {/if}
        {#if reason.trim().length > 0 && reason.trim().length < minLen}
          <span class="warn">needs at least {minLen} characters</span>
        {/if}
      </div>
      {#if error}<p class="err">{error}</p>{/if}
    </div>
    <div class="mfoot">
      <Button variant="ghost" size="sm" onclick={onCancel}>Cancel</Button>
      <Button variant={destructive ? 'destructive' : 'primary'} size="sm" disabled={!canSubmit} onclick={submit}>
        {busy ? 'Saving…' : confirmLabel}
      </Button>
    </div>
  </div>
</div>

<style>
  .scrim { position: fixed; inset: 0; z-index: 100; display: flex; align-items: center; justify-content: center; background: rgba(0, 0, 0, 0.6); padding: 20px; }
  .modal { width: 100%; max-width: 440px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: 0 16px 48px rgba(0, 0, 0, 0.6); display: flex; flex-direction: column; }
  .mhead { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 14px; border-bottom: 1px solid var(--border); }
  .mtitle { font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text); }
  .mclose { appearance: none; background: transparent; border: none; color: var(--text-faint); font-size: var(--fs-18); line-height: 1; cursor: pointer; padding: 0 4px; }
  .mclose:hover { color: var(--accent-text); }
  .mbody { padding: 14px; display: flex; flex-direction: column; gap: 12px; }
  .mhint { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); line-height: var(--lh-normal); }
  .fld { display: flex; flex-direction: column; gap: 6px; }
  .flk { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .req { color: var(--accent-text); }
  .reasons { display: flex; flex-wrap: wrap; gap: 6px; }
  .rchip { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-12); padding: 4px 9px; cursor: pointer; transition: border-color 120ms ease, background 120ms ease; }
  .rchip:hover { border-color: var(--accent); }
  .rchip.active { border-color: var(--accent); background: var(--accent-fill); color: var(--accent-text); }
  .rchip.cust { font-family: var(--font-mono); }
  .txt { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-13); padding: 7px 9px; resize: vertical; min-height: 44px; }
  .txt:focus { outline: none; border-color: var(--accent); }
  .warn { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--warn-text); }
  .err { margin: 0; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--red-text); }
  .mfoot { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 14px; border-top: 1px solid var(--border); }
</style>
