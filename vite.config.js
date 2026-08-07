import { defineConfig } from 'vite'

/**
 * The rig itself is Python. This config exists only for the documentation viewer in viz/.
 * Root is pinned to viz/ so no web tooling leaks into the application tree.
 */
export default defineConfig({
  root: 'viz',
  server: { port: 5178, open: true },
  build: { outDir: '../dist-viz', emptyOutDir: true },
  // .mmd is not a known text extension to Vite — declare it so ?raw imports work.
  assetsInclude: ['**/*.mmd'],
})
