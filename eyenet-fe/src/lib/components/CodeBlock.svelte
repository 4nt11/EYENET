<script>
  // Syntax-highlighted code block.
  //
  // Layout: one row per line. A grid synchronises the line-number cell with
  // the code cell so the two can never drift (the previous separate-<pre>
  // layout drifted by sub-pixels under certain wrap/font combinations).
  // Highlight.js runs over the whole source once, then we split the
  // rendered HTML on raw newlines to populate each row's code cell.
  // YAML/JSON/INI/HTTP tokens never span newlines, so a naive split is
  // safe for the languages we actually use.
  //
  // Editable mode: a transparent textarea overlays the whole grid,
  // aligned glyph-for-glyph with the highlighted lines. The caret's line
  // index drives a current-line highlight strip.
  //
  // Re-highlights whenever `code` or `lang` changes.
  let {
    code = $bindable(''),
    lang = null,
    editable = false,
    maxHeight = '480px',
    wrap = true,
    showLineNumbers = true,
  } = $props();

  let detected = $state(lang);
  let highlighted = $state(''); // full HTML from hljs
  let caretLine = $state(0);    // 0-indexed; -1 if no caret

  // Split source by newline for grid rows. Reactive to `code`.
  const sourceLines = $derived((code ?? '').split('\n'));
  // Highlighted HTML split by newline. Mirrors sourceLines 1:1 when hljs
  // doesn't emit tags that span lines (true for our target languages).
  const highlightedLines = $derived.by(() => {
    if (!highlighted) return sourceLines.map((l) => escapeHtml(l));
    const parts = highlighted.split('\n');
    // If hljs output's line count doesn't match the source (would happen
    // if a tag spanned a newline), fall back to plain escape.
    if (parts.length !== sourceLines.length) return sourceLines.map((l) => escapeHtml(l));
    return parts;
  });

  function escapeHtml(s) {
    return (s ?? '').replace(/[&<>"']/g, (c) => (
      c === '&' ? '&amp;' : c === '<' ? '&lt;' : c === '>' ? '&gt;' : c === '"' ? '&quot;' : '&#39;'
    ));
  }

  const lineCount = $derived(sourceLines.length);
  // How many digits the largest line number occupies. Used to pick the
  // gutter width so textarea padding can align deterministically.
  const digits = $derived(Math.max(2, String(lineCount).length));

  // JSON is the common leak payload: pretty-print before highlighting.
  const pretty = $derived.by(() => {
    if (lang === 'json' || !lang) {
      try { return JSON.stringify(JSON.parse(code), null, 2); } catch { return code; }
    }
    return code;
  });

  let hljsPromise = null;
  async function loadHljs() {
    if (hljsPromise) return hljsPromise;
    hljsPromise = (async () => {
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
        import('highlight.js/lib/languages/http'),
      ]);
      const hljs = core.default;
      for (const [name, mod] of [['json', json], ['xml', xml], ['javascript', js], ['python', py], ['bash', bash], ['sql', sql], ['ini', ini], ['yaml', yaml], ['http', http]]) {
        hljs.registerLanguage(name, mod.default);
      }
      return hljs;
    })();
    return hljsPromise;
  }

  $effect(() => {
    const src = pretty;
    const l = lang;
    let cancelled = false;
    loadHljs().then((hljs) => {
      if (cancelled) return;
      const res = l && hljs.getLanguage(l)
        ? hljs.highlight(src, { language: l })
        : hljs.highlightAuto(src);
      detected = res.language ?? l ?? 'text';
      highlighted = res.value;
    });
    return () => { cancelled = true; };
  });

  function updateCaretLine(ev) {
    const el = ev?.currentTarget ?? ev;
    if (!el) return;
    const pos = el.selectionStart ?? 0;
    // Count newlines up to the caret -> 0-indexed line.
    let line = 0;
    for (let i = 0; i < pos; i++) if (el.value.charCodeAt(i) === 10) line++;
    caretLine = line;
  }

  function onBlur() { caretLine = -1; }
</script>

<div class="cb">
  <div class="cb-bar">
    <span class="cb-lang">{detected ?? 'text'}</span>
    <span class="cb-len">{lineCount.toLocaleString()} lines · {code.length.toLocaleString()} chars{editable ? ' · editable' : ''}</span>
  </div>
  <div class="cb-body" class:cb-wrap={wrap} style="max-height:{maxHeight}; --gutter-w: calc({digits}ch + 22px + 1px);">
    <div class="cb-grid" class:no-ln={!showLineNumbers}>
      {#each highlightedLines as lineHtml, i}
        <div class="cb-row" class:active={editable && i === caretLine}>
          {#if showLineNumbers}
            <div class="cb-ln">{i + 1}</div>
          {/if}
          <div class="cb-line"><!-- hljs-escaped html -->{@html lineHtml || '&nbsp;'}</div>
        </div>
      {/each}
    </div>
    {#if editable}
      <textarea
        class="cb-ta"
        class:no-ln={!showLineNumbers}
        bind:value={code}
        oninput={updateCaretLine}
        onkeyup={updateCaretLine}
        onclick={updateCaretLine}
        onfocus={updateCaretLine}
        onblur={onBlur}
        spellcheck="false"
        autocomplete="off"
        autocapitalize="off"
        autocorrect="off"
      ></textarea>
    {/if}
  </div>
</div>

<style>
  .cb { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); overflow: hidden; position: relative; }
  .cb-bar { display: flex; align-items: center; justify-content: space-between; padding: 6px 12px; background: var(--panel); border-bottom: 1px solid var(--border); }
  .cb-lang { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--accent-text); }
  .cb-len { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }

  /* Body scrolls as a single unit. Rows live in a grid so the line-number
     column always lines up with its code cell (impossible for them to
     drift the way two separate <pre>s did). */
  .cb-body { position: relative; overflow: auto; }
  .cb-grid {
    display: grid;
    grid-template-columns: auto 1fr;
    padding: 12px 0;
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    line-height: 1.55;
    letter-spacing: var(--tracking-data);
    color: var(--text-body);
  }
  .cb-grid.no-ln { grid-template-columns: 1fr; }

  /* Each row is a subgrid (2 cells). Active row gets a subtle accent
     wash, matching the "current line" convention in code editors. */
  .cb-row {
    display: contents;
  }
  .cb-row > .cb-ln,
  .cb-row > .cb-line {
    padding-top: 0;
    padding-bottom: 0;
  }
  .cb-row.active > .cb-ln,
  .cb-row.active > .cb-line {
    background: var(--panel);
  }

  .cb-ln {
    text-align: right;
    padding-left: 12px;
    padding-right: 10px;
    color: var(--text-faint);
    user-select: none;
    border-right: 1px solid var(--border);
    background: var(--panel);
    width: var(--gutter-w);
    box-sizing: border-box;
    font-variant-numeric: tabular-nums;
  }
  .cb-grid.no-ln .cb-ln { display: none; }
  .cb-line {
    padding-left: 12px;
    padding-right: 12px;
    white-space: pre;
    min-height: 1lh;
  }
  .cb-wrap .cb-line {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  /* Editable overlay: textarea sits above the grid, glyph-aligned so the
     caret lands on exactly the same cell as the rendered code. Its left
     padding matches the grid's line-column width + 12px code padding so
     the first character of typing maps to the first column of the line.
     caret-color is restored; text is transparent (selection bg still
     shows through). */
  .cb-ta {
    position: absolute;
    inset: 0;
    margin: 0;
    padding: 12px 12px 12px calc(var(--gutter-w) + 12px);
    border: 0;
    background: transparent;
    color: transparent;
    caret-color: var(--text-body);
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    line-height: 1.55;
    letter-spacing: var(--tracking-data);
    resize: none;
    overflow: hidden;
    outline: none;
    tab-size: 2;
    white-space: pre;
  }
  .cb-wrap .cb-ta { white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word; }
  .cb-ta.no-ln { padding-left: 12px; }
  .cb-ta::selection { background: var(--accent-fill); color: transparent; }

  /* highlight.js theme, EYENET palette only. Injected HTML lacks scope,
     so :global. */
  :global(.cb-line .hljs-keyword),
  :global(.cb-line .hljs-selector-tag),
  :global(.cb-line .hljs-name),
  :global(.cb-line .hljs-attr),
  :global(.cb-line .hljs-attribute),
  :global(.cb-line .hljs-tag) { color: var(--accent-text); }
  :global(.cb-line .hljs-string),
  :global(.cb-line .hljs-number),
  :global(.cb-line .hljs-literal),
  :global(.cb-line .hljs-symbol) { color: var(--text-body); }
  :global(.cb-line .hljs-built_in),
  :global(.cb-line .hljs-type),
  :global(.cb-line .hljs-title) { color: var(--text-muted); }
  :global(.cb-line .hljs-comment),
  :global(.cb-line .hljs-meta),
  :global(.cb-line .hljs-punctuation) { color: var(--text-faint); }
  :global(.cb-line .hljs-deletion) { color: var(--red-text); }
</style>
