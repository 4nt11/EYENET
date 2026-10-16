<script>
  import DataTable from '$lib/components/DataTable.svelte';
  import Button from '$lib/components/Button.svelte';
  import { CLEARANCE_GRANTS, CLEARANCE_COLUMNS } from '$lib/data.js';
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">System</span><span class="sep">/</span><span class="slug">clearance</span></div>
      <h1>Clearance grants</h1>
    </div>
    <Button variant="primary" size="sm">Grant clearance</Button>
  </div>

  <div class="body">
    <DataTable rowKey="id" columns={CLEARANCE_COLUMNS} rows={CLEARANCE_GRANTS} />
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { flex: 0 0 auto; display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 16px 20px; border-bottom: 1px solid var(--border); }
  .crumb { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); }
  .group { color: var(--text-faint); text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .sep, .group { color: var(--text-faint); }
  .slug { color: var(--accent-text); }
  h1 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); }
  .body { flex: 1; min-height: 0; overflow: auto; padding: 16px 20px; }
</style>
