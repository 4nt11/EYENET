<script>
  import Badge from './Badge.svelte';
  // Sensitivity tier badge. normal -> neutral, restricted -> purple, classified -> red.
  // Pass `effective` to show the promoted form `classifier -> effective`.
  let { tier, effective = null, dot = true } = $props();
  const tone = (t) => (t === 'classified' ? 'critical' : t === 'restricted' ? 'high' : 'neutral');
  const promoted = $derived(effective && effective !== tier);
</script>

{#if promoted}
  <span class="promo">
    <Badge tone={tone(tier)}>{tier}</Badge>
    <span class="arr">→</span>
    <Badge tone={tone(effective)} {dot}>{effective}</Badge>
  </span>
{:else}
  <Badge tone={tone(tier)} {dot}>{tier}</Badge>
{/if}

<style>
  .promo { display: inline-flex; align-items: center; gap: 6px; }
  .arr { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
</style>
