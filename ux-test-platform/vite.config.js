import { defineConfig } from 'vite';
import { resolve } from 'path';

const __dirname = new URL('.', import.meta.url).pathname.slice(0, -1);

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        background: resolve(__dirname, 'src/background/index.js'),
        popup: resolve(__dirname, 'src/popup/index.html'),
      },
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: (chunkInfo) => {
          const name = chunkInfo.name.startsWith('_') ? `chunk${chunkInfo.name}` : chunkInfo.name;
          return `${name}.js`;
        },
        assetFileNames: (assetInfo) => {
          const rawName = assetInfo.names?.[0] ?? assetInfo.name ?? '[name]';
          const safeName = rawName.startsWith('_') ? `asset${rawName}` : rawName;
          return safeName;
        },
      },
    },
  },
});
