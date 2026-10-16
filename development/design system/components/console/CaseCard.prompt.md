Case summary card for a caseload list/grid — monospace case id, title, tier badge, and a compact meta row.

```jsx
<CaseCard
  caseId="CASE-2026-0417"
  title="Loader campaign — EMEA finance sector"
  tier="critical"
  tierLabel="CRITICAL"
  actor="UNC-3312"
  openCount={7}
  updated="12:04:51Z"
  active={selected === id}
  onClick={() => select(id)}
/>
```

`tier` drives the badge color (`critical` = red). `active` gives a purple selected state. Meta fields render only when provided.
