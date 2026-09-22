<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Button from '$lib/components/Button.svelte';
  import AuditRow from '$lib/components/AuditRow.svelte';
  import { controlLog, panicView, PANIC_EFFECTS, loadControlLog, tripPanic } from '$lib/control.svelte.js';

  let reason = $state('');
  let confirm = $state('');
  // Two gates: a reason for the audit record (server requires 1..1024) and the
  // literal PANIC confirmation. Both must be satisfied to arm the trigger.
  const armed = $derived(reason.trim().length > 0 && confirm.trim() === 'PANIC' && !panicView.submitting);

  async function trip() {
    const ok = await tripPanic(reason.trim());
    if (ok) {
      reason = '';
      confirm = '';
    }
  }

  onMount(loadControlLog);
</script>

<main>
  <SectionHeader group="System" slug="control" title="Control" />

  <div class="body">
    <!-- Panic kill-switch -->
    <div class="panic">
      <div class="phead">
        <span class="ptitle">Emergency kill-switch</span>
      </div>
      <p class="pdesc">A single system-wide stop. Irreversible from the console. Requires <code>write:panic</code>
        (a grant-only scope, never in a role baseline). When tripped it will:</p>
      <ul class="effects">
        {#each PANIC_EFFECTS as e}<li>{e}</li>{/each}
      </ul>
      <label class="fld"><span class="flabel">Reason (recorded to the audit chain)</span>
        <input class="field reason" type="text" bind:value={reason} placeholder="Why are you declaring panic?" spellcheck="false" autocomplete="off" /></label>
      <div class="trigger">
        <input class="field" type="text" bind:value={confirm} placeholder="Type PANIC to arm the trigger" spellcheck="false" autocomplete="off" />
        <Button variant="destructive" size="md" disabled={!armed} onclick={trip}>Trip kill-switch</Button>
      </div>
      {#if panicView.submitMsg}<p class="submitmsg" class:err={panicView.submitMsg.startsWith('Failed')}>{panicView.submitMsg}</p>{/if}
      <p class="warn">This fires immediately and cannot be undone from here. It emits a signed panic event that every service reacts to.</p>
    </div>

    <!-- Control history — read back from the server's hash-chained audit log -->
    <Panel title="Control history">
      {#if controlLog.rows.length}
        {#each controlLog.rows as c}
          <AuditRow {...c} />
        {/each}
      {:else}
        <p class="pnote">
          {#if !controlLog.loaded}Loading…{:else if controlLog.error}Could not load control history: {controlLog.error}{:else}No control actions recorded yet.{/if}
        </p>
      {/if}
    </Panel>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }
  .body > :global(*) { margin-bottom: 16px; }

  .panic { border: 1px solid var(--red); border-radius: var(--radius); background: var(--red-fill); padding: 16px 18px; }
  .phead { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
  .ptitle { font-family: var(--font-sans); font-size: var(--fs-16); font-weight: var(--fw-semibold); color: var(--text); }
  .pdesc { margin: 0 0 8px; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); line-height: var(--lh-normal); max-width: 80ch; }
  code { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--red-text); background: var(--surface); padding: 1px 5px; border-radius: var(--radius-sm); }
  .effects { margin: 0 0 14px; padding-left: 18px; display: flex; flex-direction: column; gap: 3px; }
  .effects li { font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-secondary); line-height: var(--lh-normal); }

  .fld { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
  .flabel { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--red-text); }
  .trigger { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .field { flex: 1; min-width: 220px; background: var(--surface); border: 1px solid var(--red); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-13); letter-spacing: var(--tracking-data); padding: 8px 12px; }
  .field.reason { font-family: var(--font-sans); letter-spacing: normal; }
  .field:focus { outline: none; border-color: var(--red-text); }
  .field::placeholder { color: var(--text-faint); font-family: var(--font-sans); letter-spacing: normal; }
  .submitmsg { margin: 12px 0 0; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }
  .submitmsg.err { color: var(--red-text); }
  .warn { margin: 12px 0 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--red-text); line-height: var(--lh-normal); }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
</style>
