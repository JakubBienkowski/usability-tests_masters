import { defineConfig } from 'vite';
import { resolve } from 'path';
import { fileURLToPath, pathToFileURL } from 'url';

const __dirname = new URL('.', import.meta.url).pathname.slice(0, -1);

export default defineConfig({
  build: {
rollupOptions: {
      input: {
        background: resolve(__dirname, 'src/background/index.js'),
        content: resolve(__dirname, 'src/content/index.js'),
        popup: resolve(__dirname, 'src/popup/index.html')
      },
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: '[name].js',
        assetFileNames: '[name].[ext]'
      }
    }
  }
});