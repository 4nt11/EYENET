<script>
  import { page } from '$app/stores';
  import { NAV } from '$lib/nav.js';

  // Section active if the path is the href or nested under it.
  const within = (href, path) => path === href || path.startsWith(href + '/');
  // Leaf active is exact, so a parent's Overview child does not light up on every sub-route.
  const exact = (href, path) => path === href;
</script>

<nav>
  {#each NAV as { group, items }}
    <div class="group">
      <div class="group-label">{group}</div>
      {#each items as item}
        {#if item.children}
          {@const open = within(item.href, $page.url.pathname)}
          <a href={item.href} class="item parent" class:active={open}>
            <span class="label">{item.label}</span>
            <span class="chev" class:open>
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 6l6 6-6 6" /></svg>
            </span>
          </a>
          {#if open}
            <div class="children">
              {#each item.children as ch}
                <a href={ch.href} class="item child" class:active={exact(ch.href, $page.url.pathname)} title={ch.desc}>
                  <span class="label">{ch.label}</span>
                </a>
              {/each}
            </div>
          {/if}
        {:else}
          <a
            href={item.href}
            class="item"
            class:active={within(item.href, $page.url.pathname)}
            class:stub={!item.built}
            class:future={item.future}
            aria-current={within(item.href, $page.url.pathname) ? 'page' : undefined}
            title={item.desc}
          >
            <span class="label">{item.label}</span>
            {#if item.future}<span class="mark" title="planned · no API yet">○</span>
            {:else if !item.built}<span class="mark" title="API exists · screen not built">·</span>{/if}
          </a>
        {/if}
      {/each}
    </div>
  {/each}
</nav>

<style>
  nav {
    width: 208px; flex: 0 0 auto;
    display: flex; flex-direction: column; gap: 4px;
    padding: 12px 8px;
    background: var(--black);
    border-right: 1px solid var(--border);
    overflow-y: auto;
  }
  .group { display: flex; flex-direction: column; gap: 1px; margin-bottom: 10px; }
  .group-label {
    padding: 6px 10px 4px;
    font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold);
    letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint);
  }
  .item {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    padding: 6px 10px;
    border-radius: var(--radius);
    border-left: 2px solid transparent;
    font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data);
    color: var(--text-muted); text-decoration: none;
    transition: background 120ms ease, color 120ms ease;
  }
  .item:hover { background: var(--panel); color: var(--text-body); }
  .item.active {
    background: var(--accent-fill); border-left-color: var(--accent-text); color: var(--accent-text);
  }
  .item.stub .label { color: var(--text-faint); }
  .item.active.stub .label, .item.active.future .label { color: var(--accent-text); }
  .mark { color: var(--text-faint); font-size: var(--fs-11); }

  .chev { display: inline-flex; color: var(--text-faint); transition: transform 120ms ease; }
  .chev.open { transform: rotate(90deg); }
  .item.active .chev { color: var(--accent-text); }

  .children { display: flex; flex-direction: column; gap: 1px; margin: 1px 0 2px 0; }
  .item.child {
    padding-left: 22px; border-left: 2px solid var(--border);
    color: var(--text-faint); font-size: var(--fs-12);
    border-radius: 0 var(--radius) var(--radius) 0;
  }
  .item.child:hover { background: var(--panel); color: var(--text-body); }
  .item.child.active { background: var(--accent-fill); border-left-color: var(--accent-text); color: var(--accent-text); }
</style>
