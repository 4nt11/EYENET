import { sveltekit } from '@sveltejs/kit/vite';

export default {
  plugins: [sveltekit()],
  server: {
    port: 5180,
    proxy: {
      // ponytail: dev-only CORS-free bridge to the local API over its self-signed TLS
      '/v1': { target: 'https://localhost:8443', changeOrigin: true, secure: false }
    }
  }
};
