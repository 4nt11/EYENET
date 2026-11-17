<div class="stub">
  <span class="tag">○ Planned</span>
  <h2>Parse failures</h2>
  <p>Lines no enabled rule could extract, grouped by shape. Backed by <code>/v1/stealer/failures</code>. One click promotes a failing line into a prefilled rule draft.</p>
  <ul>
    <li>Table: shape fingerprint · line count · first source · sample line.</li>
    <li>Row expand: raw samples (mono), inferred field hypotheses.</li>
    <li>Actions: "Draft new rule from line" · "Dismiss" (opt out of future triage).</li>
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
