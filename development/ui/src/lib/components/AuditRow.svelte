<script>
  // Immutable audit-trail row. `tamper` turns the row red and prefixes a TAMPER label.
  let { time, actor, verb, target, detail, tamper = false } = $props();
</script>

<div class="row" class:tamper>
  <span class="time">{time}</span>
  <span class="actor">{actor}</span>
  <span class="action">
    {#if tamper}<span class="flag">TAMPER</span>{/if}
    <span class="verb">{verb} </span>
    {#if target}<span class="target">{target}</span>{/if}
    {#if detail}<span class="detail"> · {detail}</span>{/if}
  </span>
</div>

<style>
  .row {
    display: grid;
    grid-template-columns: 150px 130px 1fr;
    gap: 12px;
    padding: 7px 12px;
    border-bottom: 1px solid var(--border);
    align-items: baseline;
    background: transparent;
  }
  .row.tamper { background: var(--red-fill); }
  .time {
    font-family: var(--font-mono);
    font-size: var(--fs-11);
    letter-spacing: var(--tracking-data);
    color: var(--text-faint);
    white-space: nowrap;
  }
  .actor {
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    letter-spacing: var(--tracking-data);
    color: var(--accent-text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .row.tamper .actor { color: var(--red-text); }
  .action { font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); line-height: var(--lh-normal); }
  .flag {
    font-family: var(--font-mono);
    font-size: var(--fs-11);
    font-weight: var(--fw-medium);
    letter-spacing: var(--tracking-label);
    text-transform: uppercase;
    color: var(--red-text);
    margin-right: 8px;
  }
  .verb { color: var(--text-secondary); }
  .target { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); }
  .detail { color: var(--text-faint); }
</style>
