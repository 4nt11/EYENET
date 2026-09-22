<script>
  // Framed console section: uppercase micro-label header + scrollable body.
  let { title, children, action, class: klass = '' } = $props();
</script>

<section class="panel {klass}">
  <div class="head">
    <span class="label">{title}</span>
    {@render action?.()}
  </div>
  <div class="body">{@render children?.()}</div>
</section>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    min-height: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    overflow: hidden;
  }
  .head {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 8px 12px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
  }
  .label {
    font-family: var(--font-sans);
    font-size: var(--fs-11);
    font-weight: var(--fw-semibold);
    letter-spacing: var(--tracking-label);
    text-transform: uppercase;
    color: var(--text-faint);
  }
  .body { min-height: 0; overflow: auto; }
</style>
