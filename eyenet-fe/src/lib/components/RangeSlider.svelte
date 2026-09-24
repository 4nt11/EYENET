<script>
  // Dual-thumb range slider (min + max). Two overlaid native range inputs so it
  // stays keyboard-accessible; the track fill sits between the thumbs. When a
  // thumb rests at its domain edge the caller treats that side as "unset".
  let {
    min = 0,
    max = 100,
    step = 1,
    low = $bindable(min),
    high = $bindable(max),
    label = '',
    onchange = null
  } = $props();

  const clampLow = (v) => Math.max(min, Math.min(Number(v), high));
  const clampHigh = (v) => Math.min(max, Math.max(Number(v), low));
  const span = $derived(max - min || 1);
  const lpct = $derived(((low - min) / span) * 100);
  const hpct = $derived(((high - min) / span) * 100);

  function setLow(v) { low = clampLow(v); onchange?.(); }
  function setHigh(v) { high = clampHigh(v); onchange?.(); }
</script>

<div class="rs">
  <div class="rshead">
    <span class="rslabel">{label}</span>
    <span class="rsval">{low === min ? '0' : low} – {high === max ? `${max}+` : high}</span>
  </div>
  <div class="track">
    <div class="rail"></div>
    <div class="fill" style="left:{lpct}%; right:{100 - hpct}%"></div>
    <input class="thumb" type="range" {min} {max} {step} value={low} oninput={(e) => setLow(e.target.value)} aria-label={`${label} minimum`} />
    <input class="thumb" type="range" {min} {max} {step} value={high} oninput={(e) => setHigh(e.target.value)} aria-label={`${label} maximum`} />
  </div>
</div>

<style>
  .rs { display: flex; flex-direction: column; gap: 4px; min-width: 150px; }
  .rshead { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .rslabel { font-family: var(--font-sans); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .rsval { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-body); }

  .track { position: relative; height: 18px; display: flex; align-items: center; }
  .rail { position: absolute; left: 0; right: 0; height: 3px; border-radius: 2px; background: var(--border-strong); }
  .fill { position: absolute; height: 3px; border-radius: 2px; background: var(--accent); }

  /* Two inputs share the track; only the thumbs receive pointer events so either
     one is grabbable even when they overlap. */
  .thumb { position: absolute; left: 0; right: 0; width: 100%; margin: 0; background: none; pointer-events: none; -webkit-appearance: none; appearance: none; }
  .thumb::-webkit-slider-runnable-track { background: none; }
  .thumb::-moz-range-track { background: none; }
  .thumb::-webkit-slider-thumb { pointer-events: auto; -webkit-appearance: none; appearance: none; width: 13px; height: 13px; border-radius: 50%; background: var(--text); border: 2px solid var(--accent); cursor: pointer; margin-top: -5px; }
  .thumb::-moz-range-thumb { pointer-events: auto; width: 13px; height: 13px; border-radius: 50%; background: var(--text); border: 2px solid var(--accent); cursor: pointer; }
  .thumb:focus { outline: none; }
  .thumb:focus-visible::-webkit-slider-thumb { box-shadow: 0 0 0 3px var(--accent-fill); }
</style>
