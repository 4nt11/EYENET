<script>
  import { Dialog } from 'bits-ui';
  import Button from './Button.svelte';
  import { sourceCtx } from '$lib/source.svelte.js';
  import { identityCtx } from '$lib/identity.svelte.js';
  import { collectorCreate } from '$lib/collector.svelte.js';
  // Create a collector (POST /v1/collectors, write:collectors). The create
  // leases an identity, so `kind` is taken from the chosen source and the
  // identity list is filtered to that source. `onconfirm` gets the ready payload.
  let { open = $bindable(false), onconfirm } = $props();

  let instanceName = $state('');
  let sourceId = $state('');
  let identityId = $state('');
  let notes = $state('');
  // ponytail: raw JSON config textarea, not a per-source dynamic field matrix.
  // Upgrade to typed per-kind fields (telegram_api_id, matrix_*) if operators fumble it.
  let configText = $state('{}');

  const selSource = $derived(sourceCtx.list.find((s) => s.id === sourceId) ?? null);
  // Only identities on the chosen source can back its collector; available ones
  // lease cleanly (others 409 on reuse), so surface state and float available first.
  const identities = $derived(
    sourceId
      ? identityCtx.list
          .filter((i) => i.sourceId === sourceId)
          .sort((a, b) => (a.state === 'available' ? -1 : 0) - (b.state === 'available' ? -1 : 0))
      : []
  );

  let configErr = $derived.by(() => {
    try { JSON.parse(configText || '{}'); return null; }
    catch (e) { return e.message; }
  });

  const ready = $derived(
    instanceName.trim().length >= 3 && !!sourceId && !!identityId && !configErr && !collectorCreate.submitting
  );

  // Reset on open; clear identity when the source changes (it may no longer match).
  $effect(() => { if (open) { instanceName = ''; sourceId = ''; identityId = ''; notes = ''; configText = '{}'; } });
  $effect(() => { if (identityId && !identities.some((i) => i.id === identityId)) identityId = ''; });

  async function confirm() {
    const payload = {
      instance_name: instanceName.trim(),
      kind: selSource.platform,
      source_id: sourceId,
      identity_id: identityId,
      config: JSON.parse(configText || '{}'),
      notes: notes.trim() || null
    };
    const done = await onconfirm?.(payload);
    if (done) open = false;
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Portal>
    <Dialog.Overlay class="dlg-overlay" />
    <Dialog.Content class="dlg-content">
      <div class="dlg-head">
        <Dialog.Title class="dlg-title">New collector</Dialog.Title>
      </div>
      <Dialog.Description class="dlg-desc">
        Leases one identity on the chosen source. The supervisor starts it once its desired state is set.
      </Dialog.Description>

      <label class="fld"><span class="flabel">Instance name (min 3 chars)</span>
        <input class="fin" type="text" bind:value={instanceName} placeholder="tg-collector-01" /></label>

      <label class="fld"><span class="flabel">Source</span>
        <select class="fin" bind:value={sourceId}>
          <option value="" disabled>Select a source…</option>
          {#each sourceCtx.list as s}<option value={s.id}>{s.name} · {s.platform}</option>{/each}
        </select>
        {#if !sourceCtx.list.length}<span class="hint">No sources yet — create one first.</span>{/if}
      </label>

      <label class="fld"><span class="flabel">Identity</span>
        <select class="fin" bind:value={identityId} disabled={!sourceId}>
          <option value="" disabled>{sourceId ? 'Select an identity…' : 'Pick a source first'}</option>
          {#each identities as i}<option value={i.id}>{i.name} · {i.state}</option>{/each}
        </select>
        {#if sourceId && !identities.length}<span class="hint">No identities on this source — create one first.</span>{/if}
      </label>

      <label class="fld"><span class="flabel">Config (JSON)</span>
        <textarea class="fin area" rows="3" bind:value={configText} placeholder={'{"telegram_api_id": 0}'}></textarea>
        {#if configErr}<span class="hint err">Invalid JSON: {configErr}</span>{/if}
      </label>

      <label class="fld"><span class="flabel">Notes (optional)</span>
        <input class="fin" type="text" bind:value={notes} placeholder="what this collector watches" /></label>

      {#if collectorCreate.error}<p class="hint err">Failed: {collectorCreate.error}</p>{/if}

      <div class="dlg-actions">
        <Dialog.Close class="dlg-cancel">Cancel</Dialog.Close>
        <Button variant="primary" size="sm" disabled={!ready} onclick={confirm}>Create collector</Button>
      </div>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<style>
  .fld { display: flex; flex-direction: column; gap: 4px; }
  .flabel { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .fin::placeholder { color: var(--text-faint); }
  .fin:disabled { opacity: 0.5; }
  .area { resize: vertical; font-family: var(--font-mono); font-size: var(--fs-12); }
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .hint.err { color: var(--red-text); }
  .dlg-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; margin-top: 4px; }
  .dlg-cancel { appearance: none; cursor: pointer; height: 32px; padding: 0 14px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--fs-13); }
  .dlg-cancel:hover { background: var(--panel-2); }
</style>
