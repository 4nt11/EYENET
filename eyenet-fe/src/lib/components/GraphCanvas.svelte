<script>
  import { onMount } from 'svelte';
  import cytoscape from 'cytoscape';
  import fcose from 'cytoscape-fcose';

  cytoscape.use(fcose);

  // Cytoscape render surface for the search-as-graph view. Nodes are colored by
  // entity_type (token palette), edges dashed=derived / solid=asserted with the
  // `kind` as label and `weight` → thickness. Node tap drives the detail flyout
  // (onNodeClick). In connectMode a first node tap picks the source, a second
  // picks the target and fires onConnectReady(src, dst). Tapping (or right-
  // clicking) an ASSERTED edge fires onEdgeRetract(edge); derived edges are
  // read-only. The parent persists the mutation and feeds the new edge list back.
  let {
    nodes = [],
    edges = [],
    connectMode = false,
    onNodeClick = () => {},
    onConnectReady = () => {},
    onEdgeRetract = () => {}
  } = $props();

  let container;
  let cy = null;
  let currentConnectMode = false;
  let pendingSrcId = null;

  // Resolve the entity-type palette from CSS tokens once (dark-theme values).
  const ETYPES = ['actor', 'persona', 'crew', 'case', 'group', 'thread', 'message', 'mention', 'incident', 'document', 'attachment', 'artifact'];
  function buildColorMap() {
    const cs = getComputedStyle(document.documentElement);
    const map = {};
    for (const t of ETYPES) {
      const c = cs.getPropertyValue(`--etype-${t}`).trim();
      if (c) map[t] = c;
    }
    map._default = cs.getPropertyValue('--etype-default').trim() || '#7a7d8c';
    return map;
  }
  let colorMap = {};

  const edgeKey = (e) => e.edgeId ?? `d:${e.srcId}:${e.dstId}:${e.kind}`;

  function nodeEl(n) {
    return {
      group: 'nodes',
      data: {
        id: n.id,
        label: n.title || n.id,
        etype: n.entityType,
        color: colorMap[n.entityType] ?? colorMap._default,
        raw: n
      }
    };
  }
  function edgeEl(e) {
    // weight (when present) → line thickness, clamped to stay legible.
    const w = e.weight == null ? 2 : Math.max(1.5, Math.min(6, 1 + e.weight * 3));
    return {
      group: 'edges',
      data: {
        id: edgeKey(e),
        source: e.srcId,
        target: e.dstId,
        kind: e.kind,
        provenance: e.provenance,
        w,
        raw: e
      }
    };
  }

  // Only add edges whose endpoints are actually in the node set (induced subgraph
  // guards this server-side, but a just-asserted edge must not reference a
  // missing node).
  function presentEdges() {
    const ids = new Set(nodes.map((n) => n.id));
    return edges.filter((e) => ids.has(e.srcId) && ids.has(e.dstId));
  }

  const cyStyle = () => [
    {
      selector: 'node',
      style: {
        'background-color': 'data(color)',
        label: 'data(label)',
        color: getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#dfe5e5',
        'font-family': getComputedStyle(document.documentElement).getPropertyValue('--font-sans').trim() || 'sans-serif',
        'font-size': 9,
        'text-max-width': 120,
        'text-wrap': 'ellipsis',
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'text-outline-width': 2,
        'text-outline-color': '#000000',
        width: 18,
        height: 18,
        'border-width': 1,
        'border-color': '#000000'
      }
    },
    { selector: 'node.pick-src', style: { 'border-width': 3, 'border-color': getComputedStyle(document.documentElement).getPropertyValue('--accent-text').trim() || '#a259c4' } },
    {
      selector: 'edge',
      style: {
        width: 'data(w)',
        label: 'data(kind)',
        'curve-style': 'bezier',
        'target-arrow-shape': 'triangle',
        'font-family': getComputedStyle(document.documentElement).getPropertyValue('--font-mono').trim() || 'monospace',
        'font-size': 7,
        color: getComputedStyle(document.documentElement).getPropertyValue('--text-faint').trim() || '#7a7d8c',
        'text-rotation': 'autorotate',
        'text-outline-width': 2,
        'text-outline-color': '#000000'
      }
    },
    {
      selector: 'edge[provenance = "derived"]',
      style: {
        'line-style': 'dashed',
        'line-color': getComputedStyle(document.documentElement).getPropertyValue('--edge-derived').trim() || '#4a4d57',
        'target-arrow-color': getComputedStyle(document.documentElement).getPropertyValue('--edge-derived').trim() || '#4a4d57'
      }
    },
    {
      selector: 'edge[provenance = "asserted"]',
      style: {
        'line-style': 'solid',
        'line-color': getComputedStyle(document.documentElement).getPropertyValue('--edge-asserted').trim() || '#a259c4',
        'target-arrow-color': getComputedStyle(document.documentElement).getPropertyValue('--edge-asserted').trim() || '#a259c4'
      }
    }
  ];

  function runLayout() {
    if (!cy) return;
    cy.layout({ name: 'fcose', animate: false, quality: 'default', randomize: true, nodeSeparation: 80, idealEdgeLength: 90, padding: 24 }).run();
    cy.fit(undefined, 28);
  }

  function clearPick() {
    pendingSrcId = null;
    cy?.nodes().removeClass('pick-src');
  }

  onMount(() => {
    colorMap = buildColorMap();
    cy = cytoscape({
      container,
      elements: [...nodes.map(nodeEl), ...presentEdges().map(edgeEl)],
      style: cyStyle(),
      minZoom: 0.15,
      maxZoom: 3,
      wheelSensitivity: 0.2
    });
    lastNodeSig = nodeSig();
    runLayout();

    cy.on('tap', 'node', (evt) => {
      const n = evt.target.data('raw');
      onNodeClick(n);
      if (!currentConnectMode) return;
      const id = evt.target.id();
      if (pendingSrcId == null) {
        pendingSrcId = id;
        evt.target.addClass('pick-src');
      } else if (pendingSrcId === id) {
        clearPick(); // tapped the source again → cancel
      } else {
        const src = cy.getElementById(pendingSrcId).data('raw');
        onConnectReady(src, n);
        clearPick();
      }
    });

    const onEdgeTap = (evt) => {
      const e = evt.target.data('raw');
      if (e.provenance === 'asserted') onEdgeRetract(e);
    };
    cy.on('tap', 'edge', onEdgeTap);
    cy.on('cxttap', 'edge', onEdgeTap);
    cy.on('tap', (evt) => { if (evt.target === cy) clearPick(); });

    const ro = new ResizeObserver(() => cy && cy.resize());
    ro.observe(container);

    return () => {
      ro.disconnect();
      cy?.destroy();
      cy = null;
    };
  });

  // Mirror connectMode into the closure the handlers read; clear any half-done
  // pick when the mode turns off.
  $effect(() => {
    currentConnectMode = connectMode;
    if (!connectMode) clearPick();
  });

  // Full rebuild + relayout only when the NODE set changes (a new query/facet).
  const nodeSig = () => nodes.map((n) => n.id).join('|');
  let lastNodeSig = '';
  $effect(() => {
    const sig = nodeSig();
    if (!cy || sig === lastNodeSig) return;
    lastNodeSig = sig;
    colorMap = buildColorMap();
    cy.elements().remove();
    cy.add([...nodes.map(nodeEl), ...presentEdges().map(edgeEl)]);
    clearPick();
    runLayout();
  });

  // Reconcile edges WITHOUT relayout (asserted add / retract) so mapping an edge
  // never reshuffles the canvas.
  $effect(() => {
    if (!cy) return;
    // touch `edges` so this effect tracks it
    const want = presentEdges();
    const wantIds = new Set(want.map(edgeKey));
    cy.edges().forEach((el) => { if (!wantIds.has(el.id())) el.remove(); });
    for (const e of want) {
      if (cy.getElementById(edgeKey(e)).empty()) cy.add(edgeEl(e));
    }
  });
</script>

<div class="gc" bind:this={container}></div>

<style>
  .gc { width: 100%; height: 100%; min-height: 0; background: var(--surface); }
  /* Cytoscape injects an absolutely-positioned canvas; the parent sets the box. */
  .gc :global(canvas) { outline: none; }
</style>
