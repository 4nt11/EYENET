Dense, evidence-grade data table — hairline rows, uppercase micro headers, monospace for IDs/hashes/timestamps. Use for evidence logs, indicator lists, artifact tables.

```jsx
<DataTable
  columns={[
    { key: 'ts', header: 'Timestamp', mono: true, width: '170px' },
    { key: 'indicator', header: 'Indicator', mono: true },
    { key: 'tier', header: 'Tier', render: (v) => <Badge tone={v}>{v}</Badge> },
    { key: 'src', header: 'Source', align: 'right' },
  ]}
  rows={rows}
  rowKey="id"
  selectedId={sel}
  onRowClick={(r) => setSel(r.id)}
/>
```

Mark `mono: true` on evidence columns. Pass `render` for badges/links. `onRowClick` + `selectedId` gives a purple selected row.
