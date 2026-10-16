<script>
  import { Tabs } from 'bits-ui';
  // Tabbed evidence pane (accessible via Bits UI Tabs). Consumers pass `tabs`
  // ([{ value, label }]) and place matching <Tabs.Content value="..."> blocks as
  // children (import { Tabs } from 'bits-ui' in the consumer). Bound `value`.
  let { tabs = [], value = $bindable(tabs[0]?.value), children } = $props();
</script>

<Tabs.Root bind:value class="ev">
  <Tabs.List class="ev-list">
    {#each tabs as t}
      <Tabs.Trigger value={t.value} class="ev-trig">{t.label}</Tabs.Trigger>
    {/each}
  </Tabs.List>
  {@render children?.()}
</Tabs.Root>

<style>
  :global(.ev) { display: flex; flex-direction: column; min-height: 0; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); overflow: hidden; }
  :global(.ev-list) { display: flex; gap: 2px; flex: 0 0 auto; padding: 0 6px; background: var(--panel); border-bottom: 1px solid var(--border); }
  :global(.ev-trig) {
    appearance: none; background: transparent; border: none; cursor: pointer;
    padding: 9px 12px; margin-bottom: -1px;
    font-family: var(--font-sans); font-size: var(--fs-12); font-weight: var(--fw-medium);
    letter-spacing: var(--tracking-label); text-transform: uppercase;
    color: var(--text-faint); border-bottom: 2px solid transparent;
    transition: color 120ms ease, border-color 120ms ease;
  }
  :global(.ev-trig:hover) { color: var(--text-body); }
  :global(.ev-trig[data-state="active"]) { color: var(--accent-text); border-bottom-color: var(--accent-text); }
  :global(.ev [data-tabs-content]) { min-height: 0; overflow: auto; }
</style>
