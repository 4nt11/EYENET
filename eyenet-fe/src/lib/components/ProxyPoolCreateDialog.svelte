<script>
  import { Dialog } from 'bits-ui';
  import Button from './Button.svelte';
  import Dropdown from './Dropdown.svelte';
  // Create a proxy pool (POST /v1/proxy-pools, proxy:admin). The dialog
  // mirrors CollectorCreateDialog for layout + classes so the two features
  // feel like one UI; the field set is smaller (pools are just a bag).
  // `onconfirm` is called with the ready payload; it should return a truthy
  // value on success so we close.
  let { open = $bindable(false), onconfirm } = $props();

  const KINDS = ['socks5', 'http', 'https', 'mtproxy'];

  let name = $state('');
  let kindHint = $state('');
  let description = $state('');
  let submitting = $state(false);
  let error = $state('');

  const ready = $derived(name.trim().length >= 1 && !submitting);

  $effect(() => {
    if (open) {
      name = '';
      kindHint = '';
      description = '';
      error = '';
      submitting = false;
    }
  });

  async function confirm() {
    submitting = true;
    error = '';
    try {
      const payload = {
        name: name.trim(),
        kind_hint: kindHint || null,
        description: description.trim() || null
      };
      const done = await onconfirm?.(payload);
      if (done) open = false;
    } catch (e) {
      error = e.message ?? String(e);
    } finally {
      submitting = false;
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Portal>
    <Dialog.Overlay class="dlg-overlay" />
    <Dialog.Content class="dlg-content">
      <div class="dlg-head">
        <Dialog.Title class="dlg-title">New proxy pool</Dialog.Title>
      </div>
      <Dialog.Description class="dlg-desc">
        A pool is a named bag of upstream proxies. Identities attach to a pool
        and the collector leases from it at claim time. Sticky vs rotating is
        set per-identity; the pool stays a pure container.
      </Dialog.Description>

      <label class="fld"><span class="flabel">Pool name</span>
        <input class="fin" type="text" bind:value={name} placeholder="shady-residential-1" /></label>

      <div class="fld">
        <span class="flabel">Kind hint (optional)</span>
        <Dropdown
          minWidth="100%"
          options={[{ v: '', l: '(mixed / unspecified)' }, ...KINDS.map((k) => ({ v: k, l: k }))]}
          bind:value={kindHint}
        />
        <span class="hint">Advisory label, not a filter: an operator can still drop any wire kind in.</span>
      </div>

      <label class="fld"><span class="flabel">Description (optional)</span>
        <input class="fin" type="text" bind:value={description} placeholder="what this pool is for" /></label>

      {#if error}<p class="hint err">Failed: {error}</p>{/if}

      <div class="dlg-actions">
        <Dialog.Close class="dlg-cancel">Cancel</Dialog.Close>
        <Button variant="primary" size="sm" disabled={!ready} onclick={confirm}>Create pool</Button>
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
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .hint.err { color: var(--red-text); }
  .dlg-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; margin-top: 4px; }
  .dlg-cancel { appearance: none; cursor: pointer; height: 32px; padding: 0 14px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--fs-13); }
  .dlg-cancel:hover { background: var(--panel-2); }
</style>
