<script>
  import '../app.css';
  import TopBar from '$lib/components/TopBar.svelte';
  import NavRail from '$lib/components/NavRail.svelte';
  let { children } = $props();
</script>

<div class="app">
  <TopBar />
  <div class="shell">
    <NavRail />
    <div class="content">{@render children()}</div>
  </div>
</div>

<style>
  .app { display: flex; flex-direction: column; height: 100vh; overflow: hidden; background: var(--black); }
  .shell { flex: 1; min-height: 0; display: flex; overflow: hidden; }
  .content { flex: 1; min-width: 0; display: flex; overflow: hidden; }
</style>
