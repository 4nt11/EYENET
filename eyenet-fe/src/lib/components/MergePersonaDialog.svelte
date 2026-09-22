<script>
  import { Dialog } from 'bits-ui';
  import Button from './Button.svelte';
  import { personaCtx } from '$lib/persona.svelte.js';
  // Merge THIS persona with another (POST /v1/personas/{id}/merge, async via the
  // graph worker). Pick the other persona from the list (excluding self); reason
  // is mandatory server-side. onconfirm({otherPersonaId, reason, caseRefs}).
  let { open = $bindable(false), persona = null, onconfirm } = $props();

  let otherId = $state('');
  let reason = $state('');
  let caseRefs = $state('');

  const others = $derived(persona ? personaCtx.list.filter((p) => p.id !== persona.id) : []);
  const refs = $derived(caseRefs.split(',').map((s) => s.trim()).filter(Boolean));
  const ready = $derived(!!otherId && reason.trim().length >= 16);

  $effect(() => { if (open) { otherId = ''; reason = ''; caseRefs = ''; } });

  async function confirm() {
    const done = await onconfirm?.({ otherPersonaId: otherId, reason: reason.trim(), caseRefs: refs });
    if (done) open = false;
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Portal>
    <Dialog.Overlay class="dlg-overlay" />
    <Dialog.Content class="dlg-content">
      <div class="dlg-head"><Dialog.Title class="dlg-title">Merge persona</Dialog.Title></div>
      <Dialog.Description class="dlg-desc">
        Folds another persona's actors into this one. Applied by the graph worker; cannot be undone from the console.
      </Dialog.Description>
      {#if persona}<div class="subj">into · {persona.label}</div>{/if}

      <label class="fld"><span class="flabel">Persona to merge in</span>
        <select class="fin" bind:value={otherId}>
          <option value="" disabled>Select a persona…</option>
          {#each others as o}<option value={o.id}>{o.label} · {o.memberCount} members</option>{/each}
        </select>
        {#if !others.length}<span class="hint">No other personas to merge.</span>{/if}
      </label>

      <label class="fld"><span class="flabel">Reason (min 16 chars)</span>
        <textarea class="fin area" rows="2" bind:value={reason} placeholder="Justify the merge for the audit record"></textarea></label>
      <label class="fld"><span class="flabel">Case refs</span>
        <input class="fin" type="text" bind:value={caseRefs} placeholder="CASE-2026-0417, ..." /></label>

      <div class="dlg-actions">
        <Dialog.Close class="dlg-cancel">Cancel</Dialog.Close>
        <Button variant="primary" size="sm" disabled={!ready} onclick={confirm}>Merge</Button>
      </div>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<style>
  .subj { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }
  .fld { display: flex; flex-direction: column; gap: 4px; }
  .flabel { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .fin::placeholder { color: var(--text-faint); }
  .area { resize: vertical; }
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .dlg-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; margin-top: 4px; }
  .dlg-cancel { appearance: none; cursor: pointer; height: 32px; padding: 0 14px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--fs-13); }
  .dlg-cancel:hover { background: var(--panel-2); }
</style>
