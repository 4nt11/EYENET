<script>
  import DataTable from '$lib/components/DataTable.svelte';
  import Button from '$lib/components/Button.svelte';
  import { auth } from '$lib/auth.svelte.js';

  let { data } = $props();

  // No sensitivity/tier column: the grant carries no tier field (a grant is a
  // scope grant, not a classified row). Wired from ClearanceGrantSummary only.
  const COLUMNS = [
    { key: 'grant', header: 'Grant', mono: true, width: '96px' },
    { key: 'user', header: 'User', mono: true, width: '120px' },
    { key: 'scope', header: 'Scope', mono: true },
    { key: 'grantedBy', header: 'Granted by', mono: true, width: '96px' },
    { key: 'expires', header: 'Expires', mono: true, width: '170px' },
    { key: 'status', header: 'Status', align: 'right', width: '90px', badge: true, tone: statusTone }
  ];

  // grant_id / user_id / granted_by_user_id are bare UUIDs; there is no handle
  // directory. Show a short UUID prefix so rows stay dense.
  const short = (uuid) => (uuid ? uuid.slice(0, 8) : '—');

  // Show the username only when the grant is for the signed-in operator (the one
  // UUID we can resolve to a name); every other user_id is a short UUID.
  function userLabel(userId) {
    if (auth.user && userId === auth.user.user_id) return auth.user.username;
    return short(userId);
  }

  // Status is DERIVED, not a field: revoked_at present -> revoked; else the
  // server's ACTIVE(now) predicate false, or expiry in the past -> expired;
  // else active.
  function deriveStatus(g) {
    if (g.revoked_at) return 'revoked';
    if (!g.active || new Date(g.expires_at).getTime() < Date.now()) return 'expired';
    return 'active';
  }

  const statusTone = (s) => (s === 'revoked' ? 'critical' : s === 'expired' ? 'neutral' : 'high');

  // ISO date-time -> "YYYY-MM-DD HH:mmZ" (UTC), matching the console's data style.
  const fmtTs = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}Z`;
  };

  let rows = $derived(
    (data.items ?? []).map((g) => ({
      id: g.grant_id,
      grant: short(g.grant_id),
      user: userLabel(g.user_id),
      scope: g.scope,
      grantedBy: short(g.granted_by_user_id),
      expires: fmtTs(g.expires_at),
      status: deriveStatus(g)
    }))
  );

  // /v1/clearance/grants list rejected: 401/403 = not authorized (stale token /
  // missing read scope), expected without the right token; anything else = error.
  const NOAUTH = new Set([401, 403]);
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">System</span><span class="sep">/</span><span class="slug">clearance</span></div>
      <h1>Clearance grants</h1>
    </div>
    <!-- Grant/revoke writes (admin:clearance) are a follow-up; button is a
         placeholder until the form + revoke row-action land. -->
    <Button variant="primary" size="sm" disabled>Grant clearance</Button>
  </div>

  <div class="body">
    {#if data.items && rows.length}
      <DataTable rowKey="id" columns={COLUMNS} rows={rows} />
      {#if data.total != null}
        <p class="note">
          {rows.length} shown{data.total > rows.length ? ` of ${data.total}` : ''}{data.nextCursor ? ' · more available' : ''}
        </p>
      {/if}
    {:else if data.items}
      <p class="note">No clearance grants on record.</p>
    {:else if NOAUTH.has(data.grantsStatus)}
      <p class="note">Clearance grants need a token authorised to read them. Sign in with the right scope to view.</p>
    {:else}
      <p class="note">Clearance grants unavailable (<code>/v1/clearance/grants</code> did not respond).</p>
    {/if}
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
  .note { margin: 12px 0 0; padding: 12px; border: 1px solid var(--border); font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .note code { color: var(--accent-text); }
</style>
