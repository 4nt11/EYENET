Key/value evidence panel — aligned label column, monospace values for hashes/IDs/timestamps. Use for artifact metadata, actor attributes, file details.

```jsx
<EvidencePanel
  title="Artifact"
  items={[
    { label: 'SHA-256', value: 'a3f1…9e2c' },
    { label: 'First seen', value: '2026-09-18 04:12:07Z' },
    { label: 'Classification', value: 'CRITICAL', tone: 'critical' },
    { label: 'Note', value: 'Matches known loader', mono: false },
  ]}
/>
```

Values are monospace by default; set `mono: false` for prose. `tone: 'accent' | 'critical'` tints the value. `labelWidth` adjusts the label column.
