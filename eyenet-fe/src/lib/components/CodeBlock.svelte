<script>
  import { onMount } from 'svelte';
  // Syntax-highlighted evidence dump. Auto-detects language for unlabeled leaks;
  // pretty-prints JSON first. highlight.js is lazy-imported. Theme lives below in
  // our tokens only (accent + text shades, red reserved) to hold the palette law.
  let { code = '', lang = null } = $props();

  let html = $state('');
  let detected = $state(lang);

  // JSON is the common leak payload: pretty-print before highlighting.
  let pretty = $derived.by(() => {
    if (lang === 'json' || !lang) {
      try { return JSON.stringify(JSON.parse(code), null, 2); } catch { return code; }
    }
    return code;
  });

  onMount(async () => {
    // core + only the languages actors actually dump, so the lazy chunk stays small.
    const [core, json, xml, js, py, bash, sql, ini, yaml, http] = await Promise.all([
      import('highlight.js/lib/core'),
      import('highlight.js/lib/languages/json'),
      import('highlight.js/lib/languages/xml'),
      import('highlight.js/lib/languages/javascript'),
      import('highlight.js/lib/languages/python'),
      import('highlight.js/lib/languages/bash'),
      import('highlight.js/lib/languages/sql'),
      import('highlight.js/lib/languages/ini'),
      import('highlight.js/lib/languages/yaml'),
      import('highlight.js/lib/languages/http')
    ]);
    const hljs = core.default;
    for (const [name, mod] of [['json', json], ['xml', xml], ['javascript', js], ['python', py], ['bash', bash], ['sql', sql], ['ini', ini], ['yaml', yaml], ['http', http]]) {
      hljs.registerLanguage(name, mod.default);
    }
    const src = pretty;
    const res = lang && hljs.getLanguage(lang) ? hljs.highlight(src, { language: lang }) : hljs.highlightAuto(src);
    detected = res.language ?? lang ?? 'text';
    html = res.value; // hljs escapes the source; safe to inject
  });
</script>

<div class="cb">
  <div class="cb-bar">
    <span class="cb-lang">{detected ?? 'text'}</span>
    <span class="cb-len">{code.length.toLocaleString()} chars</span>
  </div>
  <pre class="cb-pre"><code class="cb-code">{#if html}{@html html}{:else}{pretty}{/if}</code></pre>
</div>

<style>
  .cb { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); overflow: hidden; }
  .cb-bar { display: flex; align-items: center; justify-content: space-between; padding: 6px 12px; background: var(--panel); border-bottom: 1px solid var(--border); }
  .cb-lang { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--accent-text); }
  .cb-len { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .cb-pre { margin: 0; padding: 12px; overflow: auto; max-height: 480px; }
  .cb-code { font-family: var(--font-mono); font-size: var(--fs-12); line-height: 1.55; letter-spacing: var(--tracking-data); color: var(--text-body); white-space: pre; }

  /* highlight.js theme, EYENET palette only. Injected HTML lacks scope, so :global. */
  :global(.cb-code .hljs-keyword),
  :global(.cb-code .hljs-selector-tag),
  :global(.cb-code .hljs-name),
  :global(.cb-code .hljs-attr),
  :global(.cb-code .hljs-attribute),
  :global(.cb-code .hljs-tag) { color: var(--accent-text); }
  :global(.cb-code .hljs-string),
  :global(.cb-code .hljs-number),
  :global(.cb-code .hljs-literal),
  :global(.cb-code .hljs-symbol) { color: var(--text-body); }
  :global(.cb-code .hljs-built_in),
  :global(.cb-code .hljs-type),
  :global(.cb-code .hljs-title) { color: var(--text-muted); }
  :global(.cb-code .hljs-comment),
  :global(.cb-code .hljs-meta),
  :global(.cb-code .hljs-punctuation) { color: var(--text-faint); }
  :global(.cb-code .hljs-deletion) { color: var(--red-text); }
</style>
