<script>
  // Recursive editor for folder-rule predicate trees.
  //
  // Shape (eyenet/stealer/rules/matchers.py:_eval_predicate):
  //   Leaves:
  //     { path: "exact string" }                       file path equality
  //     { glob: "**/pattern" }                         glob match on path list
  //   N-ary boolean ops (children: list):
  //     { and: [...] } { or: [...] } { xor: [...] }    odd-parity xor
  //   Unary op (child: single node):
  //     { not: {...} }
  //   Counted ops (n + children):
  //     { at_least: { n: 2, children: [...] } }
  //     { exactly:  { n: 1, children: [...] } }
  //     { at_most:  { n: 3, children: [...] } }
  //
  // Each node is a single-key dict; the key names the operator or the leaf
  // kind. Mutates the `node` prop in place via Svelte 5 $state proxy
  // semantics; the parent re-renders through the $bindable.
  import Dropdown from '$lib/components/Dropdown.svelte';

  let { node = $bindable(), depth = 0, onRemove = null } = $props();

  const OP_META = {
    and:      { label: 'ALL of',           kind: 'nary' },
    or:       { label: 'ANY of',           kind: 'nary' },
    xor:      { label: 'XOR (odd count)',  kind: 'nary' },
    not:      { label: 'NOT',              kind: 'unary' },
    at_least: { label: 'at least N of',    kind: 'counted' },
    exactly:  { label: 'exactly N of',     kind: 'counted' },
    at_most:  { label: 'at most N of',     kind: 'counted' },
    path:     { label: 'path =',           kind: 'leaf' },
    glob:     { label: 'glob',             kind: 'leaf' },
  };
  // Dropdown doesn't have optgroups; cheap visual grouping via prefix.
  const OP_OPTIONS = [
    { v: 'glob',     l: 'leaf · glob' },
    { v: 'path',     l: 'leaf · path =' },
    { v: 'and',      l: 'bool · ALL of' },
    { v: 'or',       l: 'bool · ANY of' },
    { v: 'xor',      l: 'bool · XOR (odd count)' },
    { v: 'not',      l: 'bool · NOT' },
    { v: 'at_least', l: 'count · at least N of' },
    { v: 'exactly',  l: 'count · exactly N of' },
    { v: 'at_most',  l: 'count · at most N of' },
  ];

  // The single key on this node is the operator / leaf kind. Changing it
  // reshapes the node body accordingly. Bound to Dropdown via a wrapper
  // because Dropdown's value binding doesn't understand our dict-key model.
  const currentKey = $derived.by(() => Object.keys(node ?? {})[0] ?? 'glob');
  const meta = $derived(OP_META[currentKey] ?? OP_META.glob);
  let pickedKey = $state(currentKey);
  $effect(() => { pickedKey = currentKey; });

  function onKindChange() {
    const next = pickedKey;
    if (next === currentKey) return;
    const nextMeta = OP_META[next];
    for (const k of Object.keys(node)) delete node[k];
    switch (nextMeta.kind) {
      case 'leaf':    node[next] = ''; break;
      case 'nary':    node[next] = [{ glob: '' }]; break;
      case 'unary':   node[next] = { glob: '' }; break;
      case 'counted': node[next] = { n: 1, children: [{ glob: '' }] }; break;
    }
  }

  function addChild() {
    const body = node[currentKey];
    if (Array.isArray(body)) body.push({ glob: '' });
    else if (body?.children) body.children.push({ glob: '' });
  }

  function removeChildAt(i) {
    const body = node[currentKey];
    if (Array.isArray(body)) body.splice(i, 1);
    else if (body?.children) body.children.splice(i, 1);
  }

  function replaceUnary() {
    node[currentKey] = { glob: '' };
  }
</script>

<div class="pn" class:pn-root={depth === 0}>
  <div class="pn-head">
    <div class="pn-op">
      <Dropdown options={OP_OPTIONS} bind:value={pickedKey} onchange={onKindChange} minWidth="180px" />
    </div>
    {#if meta.kind === 'leaf'}
      <input
        class="pn-val mono"
        type="text"
        bind:value={node[currentKey]}
        placeholder={currentKey === 'glob' ? '**/seed.seco' : 'Wallets/MetaMask/current'}
        aria-label="{currentKey} value"
      />
    {:else if meta.kind === 'counted'}
      <label class="pn-n">
        <span>n =</span>
        <input class="pn-ni mono" type="number" min="0" bind:value={node[currentKey].n} aria-label="counted-op n" />
      </label>
    {:else}
      <span class="pn-spacer"></span>
    {/if}
    {#if onRemove}
      <button type="button" class="pn-btn pn-rm" onclick={onRemove} title="Remove this node" aria-label="Remove this node">x</button>
    {/if}
  </div>

  {#if meta.kind === 'nary'}
    <div class="pn-kids">
      {#each node[currentKey] as _c, i (i)}
        <svelte:self bind:node={node[currentKey][i]} depth={depth + 1} onRemove={() => removeChildAt(i)} />
      {/each}
      <button type="button" class="pn-btn pn-add" onclick={addChild}>+ Add child</button>
    </div>
  {:else if meta.kind === 'unary'}
    <div class="pn-kids">
      <svelte:self bind:node={node[currentKey]} depth={depth + 1} onRemove={replaceUnary} />
    </div>
  {:else if meta.kind === 'counted'}
    <div class="pn-kids">
      {#each node[currentKey].children as _c, i (i)}
        <svelte:self bind:node={node[currentKey].children[i]} depth={depth + 1} onRemove={() => removeChildAt(i)} />
      {/each}
      <button type="button" class="pn-btn pn-add" onclick={addChild}>+ Add child</button>
    </div>
  {/if}
</div>

<style>
  /* Thin accent-tinted gutter per nesting level so the tree shape reads
     at a glance. Root uses the accent border; descendants use the subtle
     divider so the eye lands on the outermost node first. */
  .pn {
    position: relative;
    padding-left: 10px;
    border-left: 2px solid var(--border);
    margin: 4px 0;
  }
  .pn-root {
    border-left-color: var(--accent);
    padding-left: 12px;
  }
  .pn-head {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 3px 0;
  }
  .pn-op { flex: 0 0 auto; }
  .pn-val {
    flex: 1;
    min-width: 0;
    height: 28px;
    background: var(--surface);
    border: 1px solid var(--border-strong);
    color: var(--text-body);
    padding: 0 8px;
    border-radius: var(--radius);
    font-family: var(--font-mono);
    font-size: var(--fs-12);
  }
  .pn-val:focus {
    outline: none;
    border-color: var(--accent);
  }
  .pn-spacer { flex: 1; }
  .pn-n {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    color: var(--text-muted);
    font-family: var(--font-sans);
    font-size: var(--fs-11);
    letter-spacing: var(--tracking-label);
    text-transform: uppercase;
  }
  .pn-ni {
    width: 56px;
    height: 24px;
    background: var(--surface);
    border: 1px solid var(--border-strong);
    color: var(--text-body);
    padding: 0 6px;
    border-radius: var(--radius);
    font-family: var(--font-mono);
    font-size: var(--fs-12);
  }
  .pn-ni:focus {
    outline: none;
    border-color: var(--accent);
  }
  /* Svelte scopes component styles, so parent-page's .btn-ghost doesn't
     reach us. Re-derive the same look locally. */
  .pn-btn {
    height: 24px;
    padding: 0 10px;
    background: transparent;
    border: 1px solid var(--border-strong);
    color: var(--text-muted);
    border-radius: var(--radius);
    font: inherit;
    font-size: var(--fs-12);
    cursor: pointer;
  }
  .pn-btn:hover {
    background: var(--panel-2);
    color: var(--text);
  }
  .pn-rm {
    color: var(--text-faint);
  }
  .pn-rm:hover {
    color: var(--red-text);
    border-color: var(--red-text);
  }
  .pn-add {
    margin-top: 4px;
    color: var(--accent-text);
  }
  .pn-kids {
    padding-left: 10px;
  }
</style>
