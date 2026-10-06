<script>
  import { onMount } from 'svelte';
  import cytoscape from 'cytoscape';
  import fcose from 'cytoscape-fcose';
  import edgehandles from 'cytoscape-edgehandles';

  cytoscape.use(fcose);
  cytoscape.use(edgehandles);

  // Cytoscape render surface for the search-as-graph view. Nodes are colored by
  // entity_type (token palette), edges dashed=derived / solid=asserted with the
  // `kind` as label and `weight` → thickness. Node tap drives the detail flyout
  // (onNodeClick).
  //
  // Connect an operator edge by SHIFT+dragging from a source node to a target
  // node (cytoscape-edgehandles draws the ghost arrow) → onConnectReady(src,dst).
  // Tapping (or right-clicking) an ASSERTED edge fires onEdgeRetract(edge);
  // derived edges are read-only. Right-clicking empty canvas fires
  // onBackgroundContext(pos) so the parent can pop the facet menu; a plain tap on
  // empty canvas fires onCanvasTap (parent closes the menu).
  let {
    nodes = [],
    edges = [],
    onNodeClick = () => {},
    onConnectReady = () => {},
    onEdgeRetract = () => {},
    onBackgroundContext = () => {},
    onCanvasTap = () => {}
  } = $props();

  let container;
  let cy = null;
  let eh = null;

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
        'font-size': 10,
        'text-max-width': 100,
        'text-wrap': 'ellipsis',
        'text-valign': 'bottom',
        'text-margin-y': 5,
        'text-outline-width': 3,
        'text-outline-color': '#000000',
        width: 22,
        height: 22,
        'border-width': 1.5,
        'border-color': '#000000'
      }
    },
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
    },
    // edgehandles' in-flight ghost edge + preview node, themed to the asserted color.
    {
      selector: '.eh-ghost-edge, .eh-preview',
      style: {
        'line-color': getComputedStyle(document.documentElement).getPropertyValue('--edge-asserted').trim() || '#a259c4',
        'target-arrow-color': getComputedStyle(document.documentElement).getPropertyValue('--edge-asserted').trim() || '#a259c4',
        'line-style': 'solid',
        width: 2.5
      }
    },
    { selector: '.eh-source, .eh-target', style: { 'border-width': 3, 'border-color': getComputedStyle(document.documentElement).getPropertyValue('--edge-asserted').trim() || '#a259c4' } }
  ];

  function runLayout() {
    if (!cy) return;
    // With few/no edges every node is its own component; fcose tiles them. Sizing
    // tiles to their LABEL box (nodeDimensionsIncludeLabels) is what stops the
    // label pile-up, and wider separation keeps the tiling from looking cramped.
    const hasEdges = cy.edges(':not(.eh-ghost-edge)').length > 0;
    cy.layout({
      name: 'fcose',
      animate: false,
      quality: 'proof',
      randomize: true,
      nodeDimensionsIncludeLabels: true,
      packComponents: true,
      nodeSeparation: hasEdges ? 90 : 150,
      idealEdgeLength: 120,
      nodeRepulsion: 9000,
      gravity: 0.25,
      gravityRange: 3.0,
      tilingPaddingVertical: 24,
      tilingPaddingHorizontal: 24,
      padding: 32
    }).run();
    cy.fit(undefined, 32);
  }

  onMount(() => {
    colorMap = buildColorMap();
    cy = cytoscape({
      container,
      elements: [...nodes.map(nodeEl), ...presentEdges().map(edgeEl)],
      style: cyStyle(),
      minZoom: 0.15,
      maxZoom: 3,
      wheelSensitivity: 0.6, // 0.2 felt sluggish; 0.6 is a brisk but controllable zoom
      boxSelectionEnabled: false
    });
    lastNodeSig = nodeSig();
    runLayout();

    // ── Shift+drag from a node draws an edge (cytoscape-edgehandles, manual start —
    // no always-on handle). Nodes are un-grabbed ONLY for the duration of a draw and
    // re-grabbed on ehstop/mouseup/blur, so a plain left-drag is NEVER left stuck off
    // (the old keydown/keyup toggle stuck whenever a Shift keyup was missed).
    eh = cy.edgehandles({
      canConnect: (s, t) => !s.same(t),
      edgeParams: () => ({ data: { _ghost: true } }),
      snap: true,
      snapThreshold: 24,
      snapFrequency: 15,
      noEdgeEventsInDraw: true,
      disableBrowserGestures: true
    });
    eh.disableDrawMode?.(); // only our shift+mousedown eh.start() draws; plain clicks drag

    const releaseGrab = () => cy?.autoungrabify(false);
    cy.on('mousedown', 'node', (evt) => {
      if (evt.originalEvent?.shiftKey) {
        cy.autoungrabify(true); // suppress node-drag for THIS draw only
        eh.start(evt.target);
      }
    });
    cy.on('ehstop', releaseGrab);
    window.addEventListener('mouseup', releaseGrab);
    window.addEventListener('blur', releaseGrab);

    cy.on('ehcomplete', (_evt, src, tgt, added) => {
      added?.remove(); // drop the ghost; the real asserted edge comes back via the API + modal
      onConnectReady(src.data('raw'), tgt.data('raw'));
    });

    // ── Cluster drag: dragging a node pulls its LEAF (degree-1) neighbors along, so
    // moving a hub actor carries its thread spokes; dragging a leaf moves just it.
    let pullSet = null;
    let lastPos = null;
    cy.on('grab', 'node', (evt) => {
      pullSet = evt.target.neighborhood('node').filter((x) => x.degree(false) === 1);
      lastPos = { ...evt.target.position() };
    });
    cy.on('drag', 'node', (evt) => {
      if (!pullSet || !lastPos) return;
      const p = evt.target.position();
      const dx = p.x - lastPos.x;
      const dy = p.y - lastPos.y;
      lastPos = { x: p.x, y: p.y };
      pullSet.forEach((x) => {
        const xp = x.position();
        x.position({ x: xp.x + dx, y: xp.y + dy });
      });
    });
    cy.on('free', 'node', () => { pullSet = null; lastPos = null; });

    cy.on('tap', 'node', (evt) => onNodeClick(evt.target.data('raw')));

    const onEdgeTap = (evt) => {
      const e = evt.target.data('raw');
      if (e?.provenance === 'asserted') onEdgeRetract(e);
    };
    cy.on('tap', 'edge', onEdgeTap);
    cy.on('cxttap', 'edge', onEdgeTap);

    // Background: plain tap closes the facet menu; right-click opens it at the
    // pointer (container-relative renderedPosition).
    cy.on('tap', (evt) => { if (evt.target === cy) onCanvasTap(); });
    cy.on('cxttap', (evt) => { if (evt.target === cy) onBackgroundContext(evt.renderedPosition); });
    const noCtx = (e) => e.preventDefault(); // suppress the browser menu over the canvas
    container.addEventListener('contextmenu', noCtx);

    const ro = new ResizeObserver(() => cy && cy.resize());
    ro.observe(container);

    return () => {
      window.removeEventListener('mouseup', releaseGrab);
      window.removeEventListener('blur', releaseGrab);
      container.removeEventListener('contextmenu', noCtx);
      ro.disconnect();
      cy?.destroy();
      cy = null;
    };
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
    runLayout();
  });

  // Reconcile edges WITHOUT relayout (asserted add / retract) so mapping an edge
  // never reshuffles the canvas.
  $effect(() => {
    if (!cy) return;
    const want = presentEdges();
    const wantIds = new Set(want.map(edgeKey));
    cy.edges('[!_ghost]').forEach((el) => { if (!wantIds.has(el.id())) el.remove(); });
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
