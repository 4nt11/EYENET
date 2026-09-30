<script>
  // Per-message incident classification + relabel block, matching the incidents
  // page: a labeled `model` row (the classifier's verdict), an `operator` row
  // (the ground-truth correction, when present), then the correct/edit control.
  // Shared by the full reader and the category reader so it can't diverge; the
  // API call + submit state live in incident.svelte.js.
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

<div class="analysis">
  <div class="lrow">
    <span class="lk">model</span>
    <div class="badges">
      {#each message.incident_labels ?? [] as l}<Badge tone={incidentTone(l)}>{incidentLabelName(l)}</Badge>{/each}
      {#if !(message.incident_labels ?? []).length}<span class="none">none</span>{/if}
    </div>
  </div>
  {#if message.corrected_labels}
    <div class="lrow">
      <span class="lk truth">operator</span>
      <div class="badges">
        {#each message.corrected_labels as l}<Badge tone={incidentTone(l)} dot>{incidentLabelName(l)}</Badge>{/each}
        {#if !message.corrected_labels.length}<span class="none fp">false positive</span>{/if}
        {#if message.corrected_by}<span class="by">by {message.corrected_by}{message.corrected_at ? ` · ${message.corrected_at}` : ''}</span>{/if}
      </div>
    </div>
  {/if}

  <div class="relabel">
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
</div>

<style>
  .analysis { display: flex; flex-direction: column; }
  .lrow { display: flex; align-items: baseline; gap: 10px; margin: 8px 0 0; }
  .lk { font-family: var(--font-mono); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); min-width: 62px; }
  .lk.truth { color: var(--accent-text); }
  .badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .none { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .none.fp { color: var(--warn-text); }
  .by { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .relabel { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
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
