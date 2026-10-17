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
  // Right-clicking an edge fires onEdgeContext(edge, pos) and a node fires
  // onNodeContext(node, pos) so the parent pops the action menu; right-clicking empty
  // canvas fires onBackgroundContext(pos) (facet menu); a plain tap fires onCanvasTap
  // (parent closes any open menu).
  let {
    nodes = [],
    edges = [],
    onNodeClick = () => {},
    onConnectReady = () => {},
    onEdgeContext = () => {},
    onNodeContext = () => {},
    onBackgroundContext = () => {},
    onCanvasTap = () => {},
    onNodeDblClick = () => {},
    // Called once with an api handle so the parent can read live node positions
    // (for saving a graph): api.positions() -> [{ id, x, y }].
    onReady = () => {}
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
    const el = {
      group: 'nodes',
      data: {
        id: n.id,
        label: n.title || n.id,
        etype: n.entityType,
        color: colorMap[n.entityType] ?? colorMap._default,
        raw: n
      }
    };
    // A saved graph supplies x/y; carry them so runLayout can place via preset.
    if (n.x != null && n.y != null) el.position = { x: n.x, y: n.y };
    return el;
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

  // Operator-chosen layout (view toolbar LAY section). fcose is the default force tiling;
  // the rest are cytoscape built-ins.
  let layoutName = 'fcose';

  function layoutOpts() {
    if (layoutName === 'breadthfirst')
      // directed: follow the arrows for depth; grid: wrap a fat level into a block
      // instead of one mile-wide row; spacingFactor<1: compress the whole thing.
      // NOTE: no `maximal` - it crashes cytoscape on any non-DAG (our linked/related
      // edges make cycles). Deep-sinking artifacts under messages is an enrichment-edge
      // decision, not a layout one.
      return { name: 'breadthfirst', animate: false, directed: true, grid: true, spacingFactor: 0.6, padding: 32, nodeDimensionsIncludeLabels: true };
    if (layoutName === 'concentric')
      return { name: 'concentric', animate: false, padding: 32, minNodeSpacing: 24, nodeDimensionsIncludeLabels: true };
    if (layoutName === 'grid')
      return { name: 'grid', animate: false, padding: 32, avoidOverlap: true, spacingFactor: 0.7, nodeDimensionsIncludeLabels: true };
    // With few/no edges every node is its own component; fcose tiles them. Sizing
    // tiles to their LABEL box (nodeDimensionsIncludeLabels) is what stops the
    // label pile-up, and wider separation keeps the tiling from looking cramped.
    const hasEdges = cy.edges(':not(.eh-ghost-edge)').length > 0;
    // 'proof' fcose is O(expensive) and locks the thread on a big graph; drop to the
    // fast heuristic layout past the heavy threshold.
    const heavy = cy.nodes().length > HEAVY_NODE_COUNT;
    return {
      name: 'fcose',
      animate: false,
      quality: heavy ? 'default' : 'proof',
      randomize: true,
      nodeDimensionsIncludeLabels: true,
      packComponents: true,
      nodeSeparation: hasEdges ? 60 : 100,
      idealEdgeLength: 75,
      nodeRepulsion: 5000,
      gravity: 0.5,
      gravityRange: 2.6,
      tilingPaddingVertical: 24,
      tilingPaddingHorizontal: 24,
      padding: 32
    };
  }

  function runLayout(force = false) {
    if (!cy) return;
    // A loaded saved graph supplies positions for every node -> honor them (preset)
    // instead of re-tiling, so the operator's arrangement is restored. An explicit
    // LAY click forces the chosen layout even over a restored arrangement.
    if (!force && nodes.length && nodes.every((n) => n.x != null && n.y != null)) {
      cy.layout({ name: 'preset', fit: true, padding: 32 }).run();
      return;
    }
    cy.layout(layoutOpts()).run();
    cy.fit(undefined, 32);
  }

  // Spring-mesh drag (own rAF loop — cola/d3-force wouldn't track a live drag). At grab
  // EVERY edge records its CURRENT length as its rest length, so the whole graph starts
  // balanced (no reshuffle). As you drag the held node, its edges stretch and the spring
  // force propagates edge-to-edge through the connected web: neighbors move, then THEIR
  // neighbors, with velocity → the pull travels and swings. The held node is pinned to
  // the cursor while held and stays where dropped after release (no snap-back); the mesh
  // deforms/settles around it. O(edges) per frame — cheap even on big graphs.
  let sim = null;
  // Above this node count the spring-mesh sim (O(n^2) anti-overlap per frame) is
  // disabled: it would pin the main thread and crash the tab on a big graph (300+
  // authors). Cytoscape's native per-node drag still works, just without the mesh.
  const HEAVY_NODE_COUNT = 150;
  const SPRING_K = 0.035; // softer → edges visibly STRETCH during a pull then retract (rubber-band)
  const SPRING_DAMP = 0.9; // retain more velocity so the stretch/retract actually swings
  const MIN_SEP = 52; // anti-overlap floor: nodes never crowd closer than this (readability)
  const SEP_K = 0.5; // how hard overlapping nodes push apart
  function simTick() {
    if (!sim) return;
    const S = sim.state;
    const pin = sim.pinned;
    // While held, the pinned node tracks cytoscape (the cursor); after release it stays
    // put (we never integrate it), so the mesh settles around the drop point.
    if (pin != null && !sim.releasing) {
      const p = S[pin].ele.position();
      S[pin].x = p.x;
      S[pin].y = p.y;
    }
    const fx = new Float64Array(S.length);
    const fy = new Float64Array(S.length);
    for (const e of sim.edges) {
      const dx = S[e.b].x - S[e.a].x;
      const dy = S[e.b].y - S[e.a].y;
      const d = Math.hypot(dx, dy) || 0.01;
      // Pull-only, like a real rubber band: force only when STRETCHED past rest; slack
      // (no push) when compressed, so you can drag nodes closer and they stay put.
      if (d <= e.rest) continue;
      const f = (d - e.rest) * SPRING_K;
      const ux = (dx / d) * f;
      const uy = (dy / d) * f;
      fx[e.a] += ux;
      fy[e.a] += uy;
      fx[e.b] -= ux;
      fy[e.b] -= uy;
    }
    // Anti-overlap: any pair closer than MIN_SEP pushes apart. Pull-only springs have no
    // restoring force, so without this the mesh folds into an unreadable clump and never
    // re-expands. Short-range only — you can still tuck nodes close, just not overlapping;
    // and grabbing any node re-spreads an already-collapsed graph.
    for (let i = 0; i < S.length; i++) {
      for (let j = i + 1; j < S.length; j++) {
        const dx = S[i].x - S[j].x;
        const dy = S[i].y - S[j].y;
        const d = Math.hypot(dx, dy) || 0.01;
        if (d >= MIN_SEP) continue;
        const push = ((MIN_SEP - d) * SEP_K) / d;
        fx[i] += dx * push;
        fy[i] += dy * push;
        fx[j] -= dx * push;
        fy[j] -= dy * push;
      }
    }
    let energy = 0;
    for (let i = 0; i < S.length; i++) {
      if (i === pin) continue; // held/dropped node is fixed
      S[i].vx = (S[i].vx + fx[i]) * SPRING_DAMP;
      S[i].vy = (S[i].vy + fy[i]) * SPRING_DAMP;
      S[i].x += S[i].vx;
      S[i].y += S[i].vy;
      S[i].ele.position({ x: S[i].x, y: S[i].y });
      energy = Math.max(energy, Math.abs(S[i].vx) + Math.abs(S[i].vy));
    }
    if (sim.releasing && energy < 0.3) {
      sim = null;
      return;
    }
    sim.raf = requestAnimationFrame(simTick);
  }
  function startSim(node) {
    // Off when the operator disabled animations, or on a heavy graph (would crash).
    if (!animationsOn || cy.nodes().length > HEAVY_NODE_COUNT) return;
    const nodes = cy.nodes();
    const idx = new Map();
    nodes.forEach((n, i) => idx.set(n.id(), i));
    const state = nodes.map((n) => {
      const p = n.position();
      return { ele: n, x: p.x, y: p.y, vx: 0, vy: 0 };
    });
    const edges = cy
      .edges()
      .map((e) => {
        const a = idx.get(e.source().id());
        const b = idx.get(e.target().id());
        if (a == null || b == null) return null;
        const dx = state[b].x - state[a].x;
        const dy = state[b].y - state[a].y;
        return { a, b, rest: Math.hypot(dx, dy) || 1 }; // rest = current length → starts balanced
      })
      .filter(Boolean);
    sim = { state, edges, pinned: idx.get(node.id()), raf: 0, releasing: false };
    simTick();
  }
  function releaseSim() {
    if (sim) sim.releasing = true; // keep simulating so the mesh settles, then it stops itself
  }
  function killSim() {
    if (sim?.raf) cancelAnimationFrame(sim.raf);
    sim = null;
  }

  // Current render-budget mode; re-created when the graph crosses HEAVY_NODE_COUNT.
  let heavyMode = false;
  // Operator toggle (view toolbar): off = no spring-mesh at all, just native drag.
  let animationsOn = true;
  const releaseGrab = () => cy?.autoungrabify(false); // closes over the outer `cy`

  // Create (or re-create) the cytoscape instance + its handlers, with a render config
  // chosen by graph size. Small graphs render crisp (2x supersample, no viewport
  // texture, edges always drawn); heavy graphs trade that for speed (1x, textured pan,
  // edges hidden while moving). Cytoscape bakes these at construction, so crossing the
  // threshold tears down and rebuilds here.
  function buildCy() {
    heavyMode = nodes.length > HEAVY_NODE_COUNT;
    colorMap = buildColorMap();
    cy = cytoscape({
      container,
      elements: [...nodes.map(nodeEl), ...presentEdges().map(edgeEl)],
      style: cyStyle(),
      minZoom: 0.15,
      maxZoom: 3,
      wheelSensitivity: 1.5,
      boxSelectionEnabled: false,
      pixelRatio: heavyMode ? 1 : Math.max(2, (typeof window !== "undefined" && window.devicePixelRatio) || 1),
      textureOnViewport: heavyMode,
      hideEdgesOnViewport: heavyMode,
      motionBlur: false
    });
    lastNodeSig = nodeSig();
    runLayout();

    eh = cy.edgehandles({
      canConnect: (s, t) => !s.same(t),
      edgeParams: () => ({ data: { _ghost: true } }),
      snap: true,
      snapThreshold: 24,
      snapFrequency: 15,
      noEdgeEventsInDraw: true,
      disableBrowserGestures: true
    });
    eh.disableDrawMode?.();

    cy.on('mousedown', 'node', (evt) => {
      if (evt.originalEvent?.shiftKey) {
        cy.autoungrabify(true);
        eh.start(evt.target);
      }
    });
    cy.on('ehstop', releaseGrab);
    cy.on('grab', 'node', (evt) => startSim(evt.target));
    cy.on('free', 'node', releaseSim);
    cy.on('ehcomplete', (_evt, src, tgt, added) => {
      added?.remove();
      onConnectReady(src.data('raw'), tgt.data('raw'));
    });
    // ponytail: cytoscape has no native dbltap; detect two taps on the same node <300ms apart.
    let lastTapId = null;
    let lastTapAt = 0;
    cy.on('tap', 'node', (evt) => {
      const id = evt.target.id();
      const now = Date.now();
      if (id === lastTapId && now - lastTapAt < 300) {
        lastTapId = null;
        onNodeDblClick(evt.target.data('raw'));
        return;
      }
      lastTapId = id;
      lastTapAt = now;
      onNodeClick(evt.target.data('raw'));
    });
    cy.on('cxttap', 'edge', (evt) => {
      evt.stopPropagation?.();
      onEdgeContext(evt.target.data('raw'), evt.renderedPosition);
    });
    cy.on('cxttap', 'node', (evt) => {
      evt.stopPropagation?.();
      onNodeContext(evt.target.data('raw'), evt.renderedPosition);
    });
    cy.on('tap', (evt) => { if (evt.target === cy) onCanvasTap(); });
    cy.on('cxttap', (evt) => { if (evt.target === cy) onBackgroundContext(evt.renderedPosition); });
  }

  onMount(() => {
    buildCy();
    // View-control api for the parent toolbar (all read the outer cy, so they survive a
    // rebuild): positions (save), fit, relayout, freeze (lock drag), animations toggle.
    onReady({
      positions: () => cy.nodes().map((n) => ({ id: n.id(), x: n.position().x, y: n.position().y })),
      fit: () => cy?.fit(undefined, 32),
      relayout: () => runLayout(),
      setLayout: (name) => { layoutName = name; runLayout(true); },
      zoom: (factor) => {
        if (!cy) return;
        cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
      },
      setFrozen: (on) => cy?.autolock(!!on),
      setAnimations: (on) => { animationsOn = !!on; if (!on) killSim(); }
    });

    // Re-grab after any draw; these span cy rebuilds so they live on window/container.
    window.addEventListener('mouseup', releaseGrab);
    window.addEventListener('blur', releaseGrab);
    const noCtx = (e) => e.preventDefault();
    container.addEventListener('contextmenu', noCtx);
    const ro = new ResizeObserver(() => cy && cy.resize());
    ro.observe(container);

    return () => {
      window.removeEventListener('mouseup', releaseGrab);
      window.removeEventListener('blur', releaseGrab);
      container.removeEventListener('contextmenu', noCtx);
      killSim();
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
    killSim(); // a running follow would reference now-removed nodes
    // Crossed the render-budget threshold -> rebuild the instance with the right config.
    if (nodes.length > HEAVY_NODE_COUNT !== heavyMode) {
      eh = null;
      cy.destroy();
      buildCy();
      return;
    }
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
