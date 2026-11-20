<script>
  import { page } from '$app/stores';

  const TABS = [
    { href: '/tuning/stealer/families',  label: 'Families' },
    { href: '/tuning/stealer',           label: 'Rules library' },
    { href: '/tuning/stealer/workbench', label: 'Workbench' },
    { href: '/tuning/stealer/failures',  label: 'Parse failures' },
    { href: '/tuning/stealer/misses',    label: 'Parse misses' },
    { href: '/tuning/stealer/pipeline',  label: 'Normalize pipeline' }
  ];
  const isActive = (href, path) => path === href;
</script>

<main>
  <header class="head">
    <div class="crumb">
      <span class="group">Tuning</span>
      <span class="sep">/</span>
      <span class="slug">stealer</span>
    </div>
    <h1>Stealer configurations</h1>
    <p class="desc">Family detection and extraction rules for stealer-log dossiers. Workbench runs client-side; files never leave the browser.</p>
    <nav class="tabs">
      {#each TABS as t}
        <a href={t.href} class="tab" class:active={isActive(t.href, $page.url.pathname)}>{t.label}</a>
      {/each}
    </nav>
  </header>

  <section class="body">
    <slot />
  </section>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { flex: 0 0 auto; padding: 20px 20px 0; border-bottom: 1px solid var(--border); }
  .crumb { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); }
  .group { color: var(--text-faint); text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .sep { color: var(--text-faint); }
  .slug { color: var(--accent-text); }
  h1 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); }
  .desc { margin: 6px 0 14px; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); max-width: 80ch; }

  .tabs { display: flex; gap: 2px; margin-top: 10px; }
  .tab {
    padding: 8px 14px 10px;
    font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data);
    color: var(--text-muted); text-decoration: none;
    border-bottom: 2px solid transparent;
    transition: color 120ms ease, border-color 120ms ease;
  }
  .tab:hover { color: var(--text-body); }
  .tab.active { color: var(--accent-text); border-bottom-color: var(--accent-text); }

  .body { flex: 1; min-height: 0; overflow: auto; padding: 20px; }
</style>
