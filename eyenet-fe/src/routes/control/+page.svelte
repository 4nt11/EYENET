<script>
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import AuditRow from '$lib/components/AuditRow.svelte';
  import { PANIC, CONTROL_LOG } from '$lib/data.js';

  let confirm = $state('');
  const armed = $derived(confirm.trim() === 'PANIC');
</script>

<main>
  <SectionHeader group="System" slug="control" title="Control" />

  <div class="body">
    <!-- Panic kill-switch -->
    <div class="panic">
      <div class="phead">
        <span class="ptitle">Emergency kill-switch</span>
        <Badge tone={PANIC.posture === 'normal' ? 'neutral' : 'critical'} dot>posture {PANIC.posture}</Badge>
      </div>
      <p class="pdesc">A single system-wide stop. Irreversible from the console. Requires <code>write:panic</code>.
        When tripped it will:</p>
      <ul class="effects">
        {#each PANIC.effects as e}<li>{e}</li>{/each}
      </ul>
      <div class="trigger">
        <input class="field" type="text" bind:value={confirm} placeholder="Type PANIC to arm the trigger" spellcheck="false" autocomplete="off" />
        <Button variant="destructive" size="md" disabled={!armed}>Trip kill-switch</Button>
      </div>
      <p class="warn">This does not fire anything in the mockup. In production it emits a signed panic event and cannot be undone from here.</p>
    </div>

    <!-- Control history -->
    <Panel title="Control history">
      {#each CONTROL_LOG as c}
        <AuditRow {...c} />
      {/each}
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

  .trigger { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .field { flex: 1; min-width: 220px; background: var(--surface); border: 1px solid var(--red); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-13); letter-spacing: var(--tracking-data); padding: 8px 12px; }
  .field:focus { outline: none; border-color: var(--red-text); }
  .field::placeholder { color: var(--text-faint); font-family: var(--font-sans); letter-spacing: normal; }
  .warn { margin: 12px 0 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--red-text); line-height: var(--lh-normal); }
</style>
