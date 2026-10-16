<script>
  import { Dialog } from 'bits-ui';
  import Button from './Button.svelte';
  import TierBadge from './TierBadge.svelte';
  // Promote-only reclassification (POST /v1/{observations|attachments|documents}/.../reclassify).
  // Only tiers strictly above the current effective tier are offered; reason min 32;
  // a signed body is mandatory (JWT alone is 403). Mirrors the server CHECK.
  let { open = $bindable(false), subject = null, onconfirm } = $props();

  const ORDER = ['normal', 'restricted', 'classified'];
  const higher = $derived(subject ? ORDER.slice(ORDER.indexOf(subject.effective_tier) + 1) : []);

  let newTier = $state('');
  let reason = $state('');
  let context = $state('');
  let caseRefs = $state('');
  let signed = $state(false);

  const refs = $derived(caseRefs.split(',').map((s) => s.trim()).filter(Boolean));
  const ready = $derived(!!newTier && reason.trim().length >= 32 && signed);

  $effect(() => { if (open) { newTier = ''; reason = ''; context = ''; caseRefs = ''; signed = false; } });

  function confirm() {
    onconfirm?.({ new_tier: newTier, reason, viewing_context: context || null, case_refs: refs });
    open = false;
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Portal>
    <Dialog.Overlay class="dlg-overlay" />
    <Dialog.Content class="dlg-content">
      <div class="dlg-head">
        <Dialog.Title class="dlg-title">Reclassify (promote only)</Dialog.Title>
        {#if subject}<TierBadge tier={subject.classifier_tier} effective={subject.effective_tier} />{/if}
      </div>
      <Dialog.Description class="dlg-desc">
        The classifier floor never moves. This raises the operator override only, and cannot be undone from the console.
      </Dialog.Description>

      {#if subject}<div class="subj">{subject.kind} · {subject.id}</div>{/if}

      <div class="fld"><span class="flabel">New tier (must be higher)</span>
        <div class="tiers">
          {#if higher.length === 0}
            <span class="maxed">Already at the maximum tier.</span>
          {:else}
            {#each higher as t}
              <button class="tierbtn" class:sel={newTier === t} onclick={() => (newTier = t)}>{t}</button>
            {/each}
          {/if}
        </div>
      </div>

      <label class="fld"><span class="flabel">Reason (min 32 chars)</span>
        <textarea class="fin area" rows="2" bind:value={reason} placeholder="Justify the promotion for the audit record"></textarea></label>
      <label class="fld"><span class="flabel">Case refs</span>
        <input class="fin" type="text" bind:value={caseRefs} placeholder="CASE-2026-0417, ..." /></label>

      <div class="sign">
        <button class="signbtn" class:done={signed} onclick={() => (signed = true)}>{signed ? '✓ Body signed (ed25519)' : 'Sign body'}</button>
        <span class="signnote">Signed body mandatory. JWT alone is refused.</span>
      </div>

      <div class="dlg-actions">
        <Dialog.Close class="dlg-cancel">Cancel</Dialog.Close>
        <Button variant="primary" size="sm" disabled={!ready} onclick={confirm}>Promote tier</Button>
      </div>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<style>
  .subj { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }
  .fld { display: flex; flex-direction: column; gap: 4px; }
  .flabel { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .tiers { display: flex; gap: 8px; flex-wrap: wrap; }
  .tierbtn { appearance: none; cursor: pointer; padding: 6px 12px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: var(--surface); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12); text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .tierbtn.sel { border-color: var(--accent); background: var(--accent-fill); color: var(--accent-text); }
  .maxed { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .fin::placeholder { color: var(--text-faint); }
  .area { resize: vertical; }
  .sign { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .signbtn { appearance: none; cursor: pointer; padding: 6px 12px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12); }
  .signbtn.done { border-color: var(--accent); color: var(--accent-text); background: var(--accent-fill); }
  .signnote { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .dlg-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; margin-top: 4px; }
  .dlg-cancel { appearance: none; cursor: pointer; height: 32px; padding: 0 14px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--fs-13); }
  .dlg-cancel:hover { background: var(--panel-2); }
</style>
