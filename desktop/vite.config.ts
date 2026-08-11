import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build the Desktop disk plugin as a single ESM file. The core loader
// rewrites `@hermes/plugin-sdk` and `react*` imports to live shims at load
// time, so we externalize them here (never bundled).
export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: 'src/plugin.tsx',
      formats: ['es'],
      fileName: () => 'plugin.js',
    },
    rollupOptions: {
      external: [/^@hermes\/plugin-sdk/, /^react($|\/)/, /^react-dom($|\/)/],
      output: {
        assetFileNames: 'style.css',
      },
    },
    outDir: 'dist',
  },
})
