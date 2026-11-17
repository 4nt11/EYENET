<div class="stub">
  <span class="tag">○ Planned</span>
  <h2>Normalize pipeline</h2>
  <p>Global post-processing pipeline. Ordered sequence of normalize verbs applied after every rule's extract step; each rule can opt out per step.</p>
  <ul>
    <li>Reorderable list of verb instances · <code>strip_whitespace</code>, <code>lowercase</code>, <code>truncate</code>, <code>replace_re2</code>, <code>date_parse</code>, etc.</li>
    <li>Per-step field filter and optional args inline.</li>
    <li>Per-rule opt-outs listed on the right, linking back to the rule in the library.</li>
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
