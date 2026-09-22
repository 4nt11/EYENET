<script>
  import Button from './Button.svelte';
  import { login, verifyMfa } from '$lib/auth.svelte.js';

  let username = $state('');
  let password = $state('');
  let code = $state('');
  let challengeId = $state(null); // set once the server asks for an MFA code
  let error = $state('');
  let busy = $state(false);

  async function submit(e) {
    e.preventDefault();
    error = '';
    busy = true;
    try {
      if (challengeId) {
        await verifyMfa(challengeId, code);
      } else {
        const r = await login(username, password);
        if (r.mfaChallengeId) {
          challengeId = r.mfaChallengeId;
          code = '';
        }
      }
      // On success the auth store flips and the layout swaps in the app.
    } catch (err) {
      error = err.message || 'Login failed';
      if (challengeId) code = '';
    } finally {
      busy = false;
    }
  }
</script>

<div class="wrap">
  <form class="card" onsubmit={submit}>
    <div class="brand">
      <span class="mark">EYENET</span>
      <span class="tag">Don't look. Observe.</span>
    </div>

    {#if challengeId}
      <label class="field">
        <span class="lbl">Authenticator code</span>
        <input
          bind:value={code}
          inputmode="numeric"
          autocomplete="one-time-code"
          maxlength="6"
          placeholder="000000"
          disabled={busy}
          required
        />
      </label>
    {:else}
      <label class="field">
        <span class="lbl">Operator</span>
        <input bind:value={username} autocomplete="username" disabled={busy} required />
      </label>
      <label class="field">
        <span class="lbl">Password</span>
        <input
          bind:value={password}
          type="password"
          autocomplete="current-password"
          disabled={busy}
          required
        />
      </label>
    {/if}

    {#if error}<p class="err">{error}</p>{/if}

    <Button variant="primary" size="lg" type="submit" disabled={busy}>
      {busy ? 'Working...' : challengeId ? 'Verify' : 'Sign in'}
    </Button>
  </form>
</div>

<style>
  .wrap {
    height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--black);
    padding: 16px;
  }
  .card {
    width: 100%;
    max-width: 340px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 28px 24px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
  }
  .brand { display: flex; flex-direction: column; gap: 4px; margin-bottom: 4px; }
  .mark {
    font-family: var(--font-mono);
    font-size: var(--fs-22);
    font-weight: var(--fw-semibold);
    letter-spacing: var(--tracking-label);
    color: var(--accent-text);
  }
  .tag { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }

  .field { display: flex; flex-direction: column; gap: 6px; }
  .lbl {
    font-family: var(--font-sans);
    font-size: var(--fs-11);
    text-transform: uppercase;
    letter-spacing: var(--tracking-label);
    color: var(--text-faint);
  }
  input {
    height: 34px;
    padding: 0 10px;
    background: var(--surface);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    color: var(--text);
    font-family: var(--font-mono);
    font-size: var(--fs-13);
    letter-spacing: var(--tracking-data);
  }
  input:focus { outline: none; border-color: var(--accent); }
  input:disabled { opacity: 0.6; }

  .err {
    margin: 0;
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    color: var(--red);
  }
</style>
