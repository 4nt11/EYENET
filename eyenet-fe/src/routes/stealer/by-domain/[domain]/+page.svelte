<script>
  // Default tab is Credentials. Client-side redirect so SvelteKit's load-cache
  // is never in the loop (that was making bar-typed navigations serve stale
  // under HMR). Replaces history entry so the Back button lands on where the
  // operator CAME from, not on this redirect stub.
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';

  onMount(() => {
    const d = encodeURIComponent($page.params.domain);
    goto(`/stealer/by-domain/${d}/credentials`, { replaceState: true });
  });
</script>
