import adapter from '@sveltejs/adapter-static';

// ponytail: static adapter — mockups are prerendered, zero server. Swap to adapter-node when wiring a backend.
/** @type {import('@sveltejs/kit').Config} */
export default {
  kit: {
    adapter: adapter({ fallback: 'index.html' })
  }
};
