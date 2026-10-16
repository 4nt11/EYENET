<script>
  import { Dialog } from 'bits-ui';
  import Button from './Button.svelte';
  import TierBadge from './TierBadge.svelte';
  // Signed byte-access acknowledgment (POST /v1/attachments/{blob_id}/access).
  // Mock: collects reason/context/case_refs and a signature step; the confirm
  // button stays disabled until the body is "signed", mirroring the server rule
  // that a JWT alone never authorises byte access.
  let { open = $bindable(false), manifest = null, onconfirm } = $props();

  let reason = $state('');
  let context = $state('');
  let caseRefs = $state('');
  let signed = $state(false);

  const classified = $derived(manifest && manifest.tier !== 'normal');
  const refs = $derived(caseRefs.split(',').map((s) => s.trim()).filter(Boolean));
  const ready = $derived(reason.trim().length >= 16 && signed && (!classified || refs.length >= 1));

  // Reset when the dialog reopens.
  $effect(() => { if (open) { signed = false; } });

  function confirm() {
    onconfirm?.({ reason, viewing_context: context || null, case_refs: refs, signed_at: new Date().toISOString() });
    open = false;
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Portal>
    <Dialog.Overlay class="dlg-overlay" />
    <Dialog.Content class="dlg-content">
      <div class="dlg-head">
        <Dialog.Title class="dlg-title">Authorized file access</Dialog.Title>
        {#if manifest}<TierBadge tier={manifest.tier} />{/if}
      </div>
      <Dialog.Description class="dlg-desc">
        This access is signed and written to the tamper-evident journal before any byte is served.
        {#if classified}A case reference is required for non-normal evidence.{/if}
      </Dialog.Description>

      {#if manifest}
        <div class="manifest">
          <span>{manifest.content_mime}</span>
          <span>{manifest.content_size?.toLocaleString?.() ?? manifest.content_size} bytes</span>
          <span class="hash">{manifest.content_hash}</span>
        </div>
      {/if}

      <label class="fld"><span class="flabel">Reason (min 16 chars)</span>
        <input class="fin" type="text" bind:value={reason} placeholder="Why this evidence is being accessed" /></label>
      <label class="fld"><span class="flabel">Viewing context (optional)</span>
        <input class="fin" type="text" bind:value={context} placeholder="e.g. review for CASE-2026-0417" /></label>
      <label class="fld"><span class="flabel">Case refs{classified ? ' (required)' : ''}</span>
        <input class="fin" type="text" bind:value={caseRefs} placeholder="CASE-2026-0417, CASE-..." /></label>

      <div class="sign">
        <button class="signbtn" class:done={signed} onclick={() => (signed = true)}>
          {signed ? '✓ Body signed (ed25519)' : 'Sign body'}
        </button>
        <span class="signnote">JWT alone never authorises. A signed body is mandatory.</span>
      </div>

      <div class="dlg-actions">
        <Dialog.Close class="dlg-cancel">Cancel</Dialog.Close>
        <Button variant="primary" size="sm" disabled={!ready} onclick={confirm}>Access & serve bytes</Button>
      </div>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<style>
  .manifest { display: flex; flex-wrap: wrap; gap: 12px; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .manifest .hash { color: var(--text-muted); word-break: break-all; }

  .fld { display: flex; flex-direction: column; gap: 4px; }
  .flabel { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .fin::placeholder { color: var(--text-faint); }

  .sign { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .signbtn { appearance: none; cursor: pointer; padding: 6px 12px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); }
  .signbtn.done { border-color: var(--accent); color: var(--accent-text); background: var(--accent-fill); }
  .signnote { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
</style>
