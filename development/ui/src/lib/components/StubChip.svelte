<script>
  import { Tooltip } from 'bits-ui';
  // Marks a UI capability blocked on a backend route. Accent, never red.
  // `route` is the exact endpoint it waits on; children explain what is blocked.
  let { route, children } = $props();
</script>

<Tooltip.Provider delayDuration={120}>
  <Tooltip.Root>
    <Tooltip.Trigger class="stubchip">○ stub</Tooltip.Trigger>
    <Tooltip.Portal>
      <Tooltip.Content class="stub-tip" sideOffset={6}>
        <div class="tip-route">{route}</div>
        <div class="tip-msg">{@render children?.()}</div>
      </Tooltip.Content>
    </Tooltip.Portal>
  </Tooltip.Root>
</Tooltip.Provider>

<style>
  :global(.stubchip) {
    display: inline-flex; align-items: center;
    height: 18px; padding: 0 8px;
    border: 1px solid rgba(162,89,196,.4); border-radius: 999px;
    background: var(--accent-fill);
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    text-transform: uppercase; color: var(--accent-text); cursor: help;
  }
  :global(.stub-tip) {
    max-width: 320px;
    border: 1px solid var(--border-strong); border-radius: var(--radius);
    background: var(--panel-2); padding: 8px 10px; z-index: 60;
  }
  :global(.stub-tip .tip-route) { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--accent-text); margin-bottom: 4px; }
  :global(.stub-tip .tip-msg) { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-secondary); line-height: var(--lh-normal); }
</style>
