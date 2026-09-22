<script>
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import { PATS, PAT_COLUMNS, SIGNING_KEYS, KEY_COLUMNS } from '$lib/data.js';
  import { auth, logout } from '$lib/auth.svelte.js';
</script>

<main>
  <SectionHeader group="System" slug="auth" title="Auth & tokens" />

  <div class="body">
    <!-- Session -->
    <Panel title="Session">
      {#snippet action()}<Button variant="ghost" size="sm" onclick={logout}>Sign out</Button>{/snippet}
      <div class="session">
        <div class="srow"><span class="k">Operator</span><span class="v accent">{auth.user?.username ?? '—'}</span></div>
        <div class="srow"><span class="k">Role</span><span class="v">{auth.user?.role ?? '—'}</span></div>
        <div class="srow top"><span class="k">Scopes</span>
          <span class="scopes">{#each auth.user?.scopes ?? [] as s}<span class="scope">{s}</span>{/each}</span>
        </div>
      </div>
    </Panel>

    <!-- Personal access tokens -->
    <Panel title="Personal access tokens">
      {#snippet action()}<Button variant="primary" size="sm">Mint token</Button>{/snippet}
      <DataTable rowKey="id" columns={PAT_COLUMNS} rows={PATS} />
    </Panel>

    <!-- Signing keys -->
    <Panel title="Signing keys">
      {#snippet action()}<Button variant="ghost" size="sm">Register key</Button>{/snippet}
      <DataTable rowKey="id" columns={KEY_COLUMNS} rows={SIGNING_KEYS} />
    </Panel>

    <p class="note">Stream tokens are short-lived and minted on demand from an active session; they are not
      listed here. MFA enrollment and recovery are managed under Session.</p>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }
  .body > :global(*) { margin-bottom: 16px; }

  .session { padding: 4px 0; }
  .srow { display: grid; grid-template-columns: 120px 1fr; gap: 12px; align-items: baseline; padding: 7px 12px; border-bottom: 1px solid var(--border); }
  .srow.top { align-items: start; }
  .srow:last-child { border-bottom: none; }
  .k { font-family: var(--font-sans); font-size: var(--fs-12); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .v { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .v.accent { color: var(--accent-text); }
  .scopes { display: flex; flex-wrap: wrap; gap: 6px; }
  .scope { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-secondary); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 2px 7px; }

  .note { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); line-height: var(--lh-normal); max-width: 80ch; }
</style>
