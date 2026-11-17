<div class="stub">
  <span class="tag">○ Planned</span>
  <h2>Rules library</h2>
  <p>List of L1 container rules, L2 file handlers, and L3 content rules. Enable, reorder, draft new rules. Backed by <code>/v1/tuning/stealer/rules</code> once the DSL loader lands.</p>
  <ul>
    <li>Three columns, one per layer (L1 / L2 / L3).</li>
    <li>Family filter and enable/disable toggle per row.</li>
    <li>Priority drag-reorder with a hairline rail on hover.</li>
    <li>"New rule" opens the editor against a blank template.</li>
  </ul>
</div>

<style>
  .stub { max-width: 70ch; border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 16px 18px; display: flex; flex-direction: column; gap: 10px; }
  .tag { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  h2 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-18); font-weight: var(--fw-semibold); color: var(--text); }
  p { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-secondary); line-height: var(--lh-normal); }
  ul { margin: 0; padding-left: 18px; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-secondary); line-height: var(--lh-normal); }
  code { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); background: var(--surface); padding: 1px 5px; border-radius: var(--radius-sm); }
</style>
