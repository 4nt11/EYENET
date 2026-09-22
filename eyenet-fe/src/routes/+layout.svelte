<script>
  import '../app.css';
  import { onMount } from 'svelte';
  import TopBar from '$lib/components/TopBar.svelte';
  import NavRail from '$lib/components/NavRail.svelte';
  import Login from '$lib/components/Login.svelte';
  import { auth, loadMe } from '$lib/auth.svelte.js';
  let { children } = $props();

  // Validate any stored token on boot; marks auth.ready when settled.
  onMount(loadMe);
</script>

{#if !auth.ready}
  <div class="boot"><span>EYENET</span></div>
{:else if !auth.token}
  <Login />
{:else}
  <div class="app">
    <TopBar />
    <div class="shell">
      <NavRail />
      <div class="content">{@render children()}</div>
    </div>
  </div>
{/if}

<style>
  .app { display: flex; flex-direction: column; height: 100vh; overflow: hidden; background: var(--black); }
  .shell { flex: 1; min-height: 0; display: flex; overflow: hidden; }
  .content { flex: 1; min-width: 0; display: flex; overflow: hidden; }

  .boot {
    height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--black);
    font-family: var(--font-mono);
    letter-spacing: var(--tracking-label);
    color: var(--text-faint);
  }
</style>
