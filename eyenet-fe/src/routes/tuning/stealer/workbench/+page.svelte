<div class="stub">
  <span class="tag">○ Planned</span>
  <h2>Workbench</h2>
  <p>Client-side rule runner. Drop an extracted stealer-log folder; the TypeScript DSL engine evaluates loaded rules in the browser. <strong>Files never leave the browser.</strong></p>
  <ul>
    <li>Left: drop zone, L1 / L2 / L3 state, per-sample status list.</li>
    <li>Center: active rule editor with Match / Extract / Normalize sections.</li>
    <li>Right: pipeline preview textarea (url · login · password per line).</li>
    <li>Zip archives are not unpacked in the browser · extract first.</li>
  </ul>
</div>

<style>
  .stub { max-width: 70ch; border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 16px 18px; display: flex; flex-direction: column; gap: 10px; }
  .tag { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  h2 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-18); font-weight: var(--fw-semibold); color: var(--text); }
  p { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-secondary); line-height: var(--lh-normal); }
  ul { margin: 0; padding-left: 18px; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-secondary); line-height: var(--lh-normal); }
  strong { color: var(--accent-text); font-weight: var(--fw-semibold); }
</style>
