<script>
  // Shared page header: breadcrumb (group / slug) + title, with an optional action slot.
  let { group, slug, title, children } = $props();
</script>

<div class="head">
  <div>
    <div class="crumb">
      <span class="group">{group}</span>
      <span class="sep">/</span>
      <span class="slug">{slug}</span>
    </div>
    <h1>{title}</h1>
  </div>
  {@render children?.()}
</div>

<style>
  .head { flex: 0 0 auto; display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 16px 20px; border-bottom: 1px solid var(--border); }
  .crumb { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); }
  .group, .sep { color: var(--text-faint); }
  .group { text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .slug { color: var(--accent-text); }
  h1 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); }
</style>
