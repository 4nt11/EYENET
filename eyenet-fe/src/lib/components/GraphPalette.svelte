<script>
  // Maltego-style entity palette for the exploration canvas: seed from corpus (scoped
  // search), and a categorized type list. Click a type to SCOPE the search to it;
  // shift-drag onto the canvas to hand-create one (wired by the parent via onDragType).
  import User from 'phosphor-svelte/lib/User';
  import UsersThree from 'phosphor-svelte/lib/UsersThree';
  import ShareNetwork from 'phosphor-svelte/lib/ShareNetwork';
  import Hash from 'phosphor-svelte/lib/Hash';
  import ChatCircle from 'phosphor-svelte/lib/ChatCircle';
  import ChatsCircle from 'phosphor-svelte/lib/ChatsCircle';
  import CircleDashed from 'phosphor-svelte/lib/CircleDashed';
  import Globe from 'phosphor-svelte/lib/Globe';
  import GlobeHemisphereWest from 'phosphor-svelte/lib/GlobeHemisphereWest';
  import LinkSimple from 'phosphor-svelte/lib/LinkSimple';
  import TreeStructure from 'phosphor-svelte/lib/TreeStructure';
  import Broadcast from 'phosphor-svelte/lib/Broadcast';
  import Envelope from 'phosphor-svelte/lib/Envelope';
  import CurrencyBtc from 'phosphor-svelte/lib/CurrencyBtc';
  import CurrencyCircleDollar from 'phosphor-svelte/lib/CurrencyCircleDollar';
  import Coins from 'phosphor-svelte/lib/Coins';
  import CaretLeft from 'phosphor-svelte/lib/CaretLeft';
  import CaretRight from 'phosphor-svelte/lib/CaretRight';
  import { explorer, seedSearch, addSeed, setSeedScope } from '$lib/explorer.svelte.js';
  import { ui, togglePalette } from '$lib/ui.svelte.js';
  import { kindLabel, entityTypeLabel } from '$lib/labels.js';

  // Human label for a search hit: the artifact KIND (Onion/URL/...) is more useful
  // than the generic "Artifact"; everything else uses its entity-type label.
  const hitLabel = (h) =>
    h.entity_type === 'artifact' && h.fields?.kind ? kindLabel(h.fields.kind) : entityTypeLabel(h.entity_type);

  // The page listens for a drop on the canvas and opens the create modal preset to
  // the dragged type; the payload travels via dataTransfer.
  const DRAG_MIME = 'application/x-eyenet-entity';

  // scope = the entity_type the row scopes search to. create = how +New seeds it:
  // { kind:'actor'|'group'|'artifact', artifactKind? } for shift-drag creation.
  const GROUPS = [
    {
      title: 'Identity',
      items: [
        { label: 'Actor', desc: 'A handle/account seen in a source', icon: User, color: 'var(--etype-actor)', scope: { id: 'actor', types: 'actor' }, create: { kind: 'actor' } },
        { label: 'Persona', desc: 'Confirmed same-person cluster of actors', icon: UsersThree, color: 'var(--etype-persona)', scope: { id: 'persona', types: 'persona' }, create: { kind: 'persona' } },
        { label: 'Crew', desc: 'A named group of collaborating actors', icon: ShareNetwork, color: 'var(--etype-crew)', scope: { id: 'crew', types: 'crew' }, create: { kind: 'crew' } }
      ]
    },
    {
      title: 'Content',
      items: [
        { label: 'Group', desc: 'A forum board or channel', icon: Hash, color: 'var(--etype-group)', scope: { id: 'group', types: 'group' }, create: { kind: 'group' } },
        { label: 'Thread', desc: 'A forum thread / conversation', icon: ChatsCircle, color: 'var(--etype-thread)', scope: { id: 'thread', types: 'thread' } },
        { label: 'Message', desc: 'A single post or message', icon: ChatCircle, color: 'var(--etype-message)', scope: { id: 'message', types: 'message' } }
      ]
    },
    {
      title: 'Infrastructure',
      items: [
        { label: 'onion', desc: 'A v3 .onion hidden service', icon: CircleDashed, color: '#b26bff', scope: { id: 'onion', dsl: 'artifact.kind:onion' }, create: { kind: 'artifact', artifactKind: 'onion' } },
        { label: 'domain', desc: 'A registered domain', icon: Globe, color: '#45a6ff', scope: { id: 'domain', dsl: 'artifact.kind:domain' }, create: { kind: 'artifact', artifactKind: 'domain' } },
        { label: 'url', desc: 'A full URL (host + path)', icon: LinkSimple, color: '#53d97a', scope: { id: 'url', dsl: 'artifact.kind:url' }, create: { kind: 'artifact', artifactKind: 'url' } },
        { label: 'fqdn', desc: 'Fully-qualified host (subdomain)', icon: TreeStructure, color: '#2fd1c4', scope: { id: 'fqdn', dsl: 'artifact.kind:fqdn' }, create: { kind: 'artifact', artifactKind: 'fqdn' } },
        { label: 'IPv4', desc: 'An IPv4 address', icon: Broadcast, color: '#45a6ff', scope: { id: 'ipv4', dsl: 'artifact.kind:ipv4' }, create: { kind: 'artifact', artifactKind: 'ipv4' } },
        { label: 'IPv6', desc: 'An IPv6 address', icon: GlobeHemisphereWest, color: '#6d8bff', scope: { id: 'ipv6', dsl: 'artifact.kind:ipv6' }, create: { kind: 'artifact', artifactKind: 'ipv6' } },
        { label: 'email', desc: 'An email address', icon: Envelope, color: '#45a6ff', scope: { id: 'email', dsl: 'artifact.kind:email' }, create: { kind: 'artifact', artifactKind: 'email' } },
        { label: 'BTC wallet', desc: 'A Bitcoin address', icon: CurrencyBtc, color: '#ffb43d', scope: { id: 'wallet_btc', dsl: 'artifact.kind:wallet_btc' }, create: { kind: 'artifact', artifactKind: 'wallet_btc' } },
        { label: 'XMR wallet', desc: 'A Monero address', icon: CurrencyCircleDollar, color: '#ff8a3d', scope: { id: 'wallet_xmr', dsl: 'artifact.kind:wallet_xmr' }, create: { kind: 'artifact', artifactKind: 'wallet_xmr' } },
        { label: 'TRON wallet', desc: 'A TRON address', icon: Coins, color: '#ff6f9d', scope: { id: 'wallet_tron', dsl: 'artifact.kind:wallet_tron' }, create: { kind: 'artifact', artifactKind: 'wallet_tron' } }
      ]
    }
  ];

  let q = $state('');
  let timer;
  $effect(() => {
    const term = q;
    clearTimeout(timer);
    timer = setTimeout(() => seedSearch(term), 200);
    return () => clearTimeout(timer);
  });

  function dropResult(hit) {
    addSeed(hit);
    q = '';
    explorer.seedResults = [];
  }
  const isActive = (it) => explorer.seedScope?.id === it.scope.id;
</script>

{#if ui.paletteCollapsed}
  <aside class="palette collapsed">
    <button class="p-toggle" onclick={togglePalette} title="Expand palette" aria-label="Expand palette">
      <CaretRight size={16} weight="bold" />
    </button>
  </aside>
{:else}
<aside class="palette">
  <div class="p-head">
    <span>Entity Palette</span>
    <button class="p-toggle" onclick={togglePalette} title="Collapse palette" aria-label="Collapse palette">
      <CaretLeft size={16} weight="bold" />
    </button>
  </div>

  <input class="p-search" type="search" bind:value={q} placeholder="Seed from corpus…" spellcheck="false" />

  {#if explorer.seedLoading}
    <div class="p-note">Searching…</div>
  {:else if explorer.seedResults.length}
    <div class="p-results">
      {#each explorer.seedResults as hit (hit.entity_id)}
        <button class="p-result" onclick={() => dropResult(hit)}>
          <span class="dot" style="background:var(--etype-{hit.entity_type}, var(--etype-default))"></span>
          <span class="r-title">{hit.title || hit.entity_id}</span>
          <span class="r-type">{hitLabel(hit)}</span>
        </button>
      {/each}
    </div>
  {:else}
    <p class="p-hint"><kbd>Shift</kbd>-drag a type onto the canvas to add your own entity. Click a type to scope the search.</p>
  {/if}

  <div class="p-list">
    {#each GROUPS as g}
      <div class="p-group">{g.title}</div>
      {#each g.items as it}
        {@const Icon = it.icon}
        <button
          class="p-item" class:active={isActive(it)}
          draggable={!!it.create}
          ondragstart={(e) => it.create && e.dataTransfer?.setData(DRAG_MIME, JSON.stringify(it.create))}
          onclick={() => setSeedScope(it.scope)}
          title={it.create ? 'Click to scope search · drag onto canvas to create' : 'Click to scope search'}
        >
          <span class="glyph" style="color:{it.color}; border-color:{it.color}"><Icon size={16} weight="bold" /></span>
          <span class="i-text">
            <span class="i-name">{it.label}</span>
            <span class="i-desc">{it.desc}</span>
          </span>
        </button>
      {/each}
    {/each}
  </div>
</aside>
{/if}

<style>
  .palette { width: 240px; flex: 0 0 240px; height: 100%; display: flex; flex-direction: column; overflow: hidden; background: var(--panel-2, var(--surface)); border-right: 1px solid var(--border-strong); }
  .palette.collapsed { width: 32px; flex: 0 0 32px; align-items: center; padding-top: 8px; }
  .p-head { display: flex; align-items: center; justify-content: space-between; }
  .p-toggle { display: grid; place-items: center; width: 24px; height: 24px; padding: 0; background: none; border: 1px solid transparent; border-radius: var(--radius-sm, 3px); color: var(--text-faint); cursor: pointer; }
  .p-toggle:hover { border-color: var(--border-strong); color: var(--accent-text); }
  .p-head { flex: 0 0 auto; padding: 12px 14px 8px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .p-search { margin: 0 12px 8px; height: 30px; padding: 0 10px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12); }
  .p-search:focus { outline: none; border-color: var(--accent); }
  .p-hint { margin: 0 14px 10px; font-family: var(--font-sans); font-size: var(--fs-11); line-height: var(--lh-normal); color: var(--text-faint); }
  .p-hint kbd { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-body); border: 1px solid var(--border-strong); border-radius: 3px; padding: 0 4px; }
  .p-note { margin: 0 14px 10px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); }

  .p-results { margin: 0 8px 8px; max-height: 240px; overflow-y: auto; border: 1px solid var(--border); border-radius: var(--radius); }
  .p-result { display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px 8px; background: none; border: 0; border-bottom: 1px solid var(--border); cursor: pointer; text-align: left; }
  .p-result:hover { background: var(--surface); }
  .r-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-body); }
  .r-type { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .dot { flex: 0 0 auto; width: 8px; height: 8px; border-radius: 50%; }

  .p-list { flex: 1; min-height: 0; overflow-y: auto; padding-bottom: 12px; }
  .p-group { padding: 12px 14px 4px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .p-item { display: flex; align-items: center; gap: 10px; width: 100%; padding: 6px 12px; background: none; border: 0; border-left: 2px solid transparent; cursor: grab; text-align: left; }
  .p-item:hover { background: var(--surface); }
  .p-item.active { border-left-color: var(--accent); background: var(--surface); }
  .glyph { flex: 0 0 auto; display: grid; place-items: center; width: 26px; height: 26px; border: 1px solid; border-radius: 6px; background: color-mix(in srgb, currentColor 14%, transparent); }
  .i-text { display: flex; flex-direction: column; min-width: 0; }
  .i-name { font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text); }
  .i-desc { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
