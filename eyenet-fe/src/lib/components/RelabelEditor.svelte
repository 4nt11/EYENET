<script>
  // Per-message incident relabel editor — the operator ground-truth flow, shared
  // by the full reader (reader/group) and the category reader (reader/category)
  // so the correction UI can't diverge. The API call + submit state live in
  // incident.svelte.js; this owns only the per-message editing state + markup.
  import Badge from './Badge.svelte';
  import { incidentLabelName, incidentTone, INCIDENT_LABELS } from '$lib/data.js';
  import { relabelIncident, incidentEdit } from '$lib/incident.svelte.js';

  let { message } = $props();

  const REASON_PRESETS = ['False positive', 'Incorrectly tagged', 'Missing label', 'Partially correct'];
  let editing = $state(false);
  let draft = $state(new Set());
  let reason = $state('');
  let customReason = $state(false);
  const canSave = $derived(reason.trim().length > 0 && !incidentEdit.submitting);

  function start() {
    editing = true;
    draft = new Set(message.corrected_labels ?? message.incident_labels ?? []);
    reason = '';
    customReason = false;
  }
  function toggle(l) {
    const n = new Set(draft);
    n.has(l) ? n.delete(l) : n.add(l);
    draft = n;
  }
  async function save() {
    const labels = INCIDENT_LABELS.filter((l) => draft.has(l));
    const ok = await relabelIncident(message.id, labels, reason.trim());
    if (ok) {
      message.corrected_labels = labels; // reflect the correction inline
      editing = false;
    }
  }
</script>

<div class="relabel">
  {#if message.corrected_labels}
    <div class="corrected">
      <span class="corrtag">operator</span>
      {#each message.corrected_labels as l}<Badge tone={incidentTone(l)} dot>{incidentLabelName(l)}</Badge>{/each}
      {#if !message.corrected_labels.length}<Badge tone="neutral" dot>false positive</Badge>{/if}
    </div>
  {/if}
  {#if editing}
    <div class="chips">
      {#each INCIDENT_LABELS as l}
        <button type="button" class="chip" class:on={draft.has(l)} onclick={() => toggle(l)}>{incidentLabelName(l)}</button>
      {/each}
    </div>
    <div class="chips">
      {#each REASON_PRESETS as r}
        <button type="button" class="chip" class:on={!customReason && reason === r} onclick={() => { reason = r; customReason = false; }}>{r}</button>
      {/each}
      <button type="button" class="chip" class:on={customReason} onclick={() => { customReason = true; reason = ''; }}>Custom…</button>
    </div>
    {#if customReason}<input class="fin" type="text" bind:value={reason} placeholder="Custom reason (recorded to the audit chain)" />{/if}
    <div class="ra">
      <button class="btn" disabled={!canSave} onclick={save}>Save correction</button>
      <button class="btn ghost" onclick={() => (editing = false)}>Cancel</button>
      <span class="hint">reason required · empty labels = false positive</span>
    </div>
  {:else}
    <button class="editlink" onclick={start}>{message.corrected_labels ? 'edit correction' : 'correct labels'}</button>
  {/if}
  {#if editing && incidentEdit.msg}<span class="hint" class:err={incidentEdit.msg.startsWith('Failed')}>{incidentEdit.msg}</span>{/if}
</div>

<style>
  .relabel { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
  .corrected { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
  .corrtag { font-family: var(--font-sans); font-size: var(--fs-10); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--accent-text); }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { background: var(--surface); border: 1px solid var(--border-strong); border-radius: 4px; color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--fs-11); padding: 2px 8px; cursor: pointer; }
  .chip.on { background: var(--accent-fill); border-color: var(--accent); color: var(--text-body); }
  .ra { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .editlink { background: none; border: none; color: var(--text-faint); font-family: var(--font-sans); font-size: var(--fs-11); text-decoration: underline; cursor: pointer; padding: 0; }
  .editlink:hover { color: var(--accent); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; min-width: 260px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .btn { background: var(--accent); color: var(--black); border: none; border-radius: var(--radius); font-family: var(--font-sans); font-size: var(--fs-12); padding: 6px 12px; cursor: pointer; }
  .btn.ghost { background: transparent; color: var(--text-secondary); border: 1px solid var(--border-strong); }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .hint.err { color: var(--red-text); }
</style>
