<script>
  import Button from './Button.svelte';
  import Dropdown from './Dropdown.svelte';

  // Edge edit modal, two modes:
  //   mode="connect" — map a new asserted edge A→B. Pick a `kind` (preset or
  //     freetext "other") + a REQUIRED reason, then onConfirm(kind, reason).
  //   mode="retract" — remove an asserted edge. REQUIRED reason, onConfirm(reason).
  // `busy`/`error` reflect the in-flight POST/DELETE so the modal can disable +
  // surface the problem+json detail. `src`/`dst` label the endpoints (connect);
  // `edge` labels the target (retract).
  let { mode = 'connect', src = null, dst = null, edge = null, busy = false, error = null, onConfirm, onCancel } = $props();

  const KINDS = [
    { v: 'associate', l: 'associate' },
    { v: 'communicates_with', l: 'communicates_with' },
    { v: 'same_crew', l: 'same_crew' },
    { v: 'other', l: 'other (freetext)…' }
  ];

  let kindSel = $state('associate');
  let kindOther = $state('');
  let reason = $state('');

  const cap = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);
  const nodeLabel = (n) => (n ? `${cap(n.entityType)} · ${n.title || n.id}` : '—');

  let resolvedKind = $derived(kindSel === 'other' ? kindOther.trim() : kindSel);
  let canSubmit = $derived(
    reason.trim().length > 0 && (mode === 'retract' || resolvedKind.length > 0) && !busy
  );

  function submit() {
    if (!canSubmit) return;
    if (mode === 'retract') onConfirm(reason.trim());
    else onConfirm(resolvedKind, reason.trim());
  }
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onCancel()} />

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="scrim" role="presentation" onclick={onCancel}>
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions -->
  <div class="modal" role="dialog" tabindex="-1" aria-modal="true" aria-label={mode === 'retract' ? 'Remove edge' : 'Map edge'} onclick={(e) => e.stopPropagation()}>
    <div class="mhead">
      <span class="mtitle">{mode === 'retract' ? 'Remove asserted edge' : 'Map edge'}</span>
      <button class="mclose" onclick={onCancel} aria-label="Cancel">×</button>
    </div>

    <div class="mbody">
      {#if mode === 'connect'}
        <div class="endpoints">
          <div class="ep"><span class="epk">From</span><span class="epv">{nodeLabel(src)}</span></div>
          <div class="arrow">→</div>
          <div class="ep"><span class="epk">To</span><span class="epv">{nodeLabel(dst)}</span></div>
        </div>

        <label class="fld">
          <span class="flk">Kind</span>
          <Dropdown options={KINDS} bind:value={kindSel} minWidth="100%" />
        </label>
        {#if kindSel === 'other'}
          <label class="fld">
            <span class="flk">Custom kind</span>
            <input class="txt" bind:value={kindOther} placeholder="e.g. shares_infrastructure" spellcheck="false" />
          </label>
        {/if}
      {:else}
        <div class="endpoints solo">
          <div class="ep"><span class="epk">Edge</span><span class="epv">{edge?.kind ?? '—'}</span></div>
        </div>
        <p class="warn">This permanently retracts an operator-mapped edge. Derived edges can't be removed.</p>
      {/if}

      <label class="fld">
        <span class="flk">Reason <span class="req">required</span></span>
        <textarea class="txt area" bind:value={reason} rows="2" placeholder={mode === 'retract' ? 'Why is this edge wrong?' : 'Why are these linked? (audited)'}></textarea>
      </label>

      {#if error}<p class="err">{error}</p>{/if}
    </div>

    <div class="mfoot">
      <Button variant="ghost" size="sm" onclick={onCancel}>Cancel</Button>
      <Button variant={mode === 'retract' ? 'destructive' : 'primary'} size="sm" disabled={!canSubmit} onclick={submit}>
        {#if busy}Saving…{:else if mode === 'retract'}Remove edge{:else}Map edge{/if}
      </Button>
    </div>
  </div>
</div>

<style>
  .scrim { position: fixed; inset: 0; z-index: 100; display: flex; align-items: center; justify-content: center; background: rgba(0, 0, 0, 0.6); padding: 20px; }
  .modal { width: 100%; max-width: 420px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: 0 16px 48px rgba(0, 0, 0, 0.6); display: flex; flex-direction: column; }
  .mhead { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 14px; border-bottom: 1px solid var(--border); }
  .mtitle { font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text); }
  .mclose { appearance: none; background: transparent; border: none; color: var(--text-faint); font-size: var(--fs-18); line-height: 1; cursor: pointer; padding: 0 4px; }
  .mclose:hover { color: var(--accent-text); }

  .mbody { padding: 14px; display: flex; flex-direction: column; gap: 12px; }
  .endpoints { display: flex; align-items: center; gap: 10px; }
  .endpoints.solo { display: block; }
  .ep { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .epk { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .epv { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .arrow { color: var(--accent-text); font-size: var(--fs-16); flex: 0 0 auto; }

  .fld { display: flex; flex-direction: column; gap: 5px; }
  .flk { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .req { color: var(--accent-text); }
  .txt { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-13); padding: 7px 9px; }
  .txt:focus { outline: none; border-color: var(--accent); }
  .area { resize: vertical; min-height: 44px; }

  .warn { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--warn-text); line-height: var(--lh-normal); }
  .err { margin: 0; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--red-text); }

  .mfoot { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 14px; border-top: 1px solid var(--border); }
</style>
