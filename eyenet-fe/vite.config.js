import { sveltekit } from '@sveltejs/kit/vite';

export default {
  plugins: [sveltekit()],
  // ponytail: @adguard/re2-wasm ships an emscripten wrapper whose binary
  // Vite can't trace through the CJS require. Workbench grabs the .wasm
  // via a '?url' import and shims Module.locateFile BEFORE loading the
  // engine. assetsInclude ensures .wasm files are copied as plain assets.
  assetsInclude: ['**/*.wasm'],
  server: {
    port: 5180,
    proxy: {
      // ponytail: dev-only CORS-free bridge to the local API over its self-signed TLS
      '/v1': { target: 'https://localhost:8443', changeOrigin: true, secure: false }
    }
  }
};
