Console action button — primary (purple) for the main action, destructive (red) for tamper/delete, ghost/quiet for secondary controls.

```jsx
<Button variant="primary" size="md" onClick={commit}>Confirm classification</Button>
<Button variant="destructive" size="sm">Purge evidence</Button>
<Button variant="ghost">Export</Button>
<Button variant="quiet">Cancel</Button>
```

Variants: `primary` | `destructive` | `ghost` | `quiet`. Sizes: `sm` | `md` | `lg`. Pass `icon` for a leading 14px glyph, `disabled` to dim. Red is reserved for destructive/tamper actions only.
