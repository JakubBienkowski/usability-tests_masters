import { defineConfig } from 'vite';
import { resolve } from 'path';

const __dirname = new URL('.', import.meta.url).pathname.slice(0, -1);

export default defineConfig({
  publicDir: false,
  build: {
    outDir: 'dist',
    emptyOutDir: false,
    lib: {
      entry: resolve(__dirname, 'src/content/index.js'),
      name: 'UxTestPlatformContent',
      formats: ['iife'],
      fileName: () => 'content.js',
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
  },
});
