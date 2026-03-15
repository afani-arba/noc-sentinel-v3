import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [
    react({
      // Allow JSX in .js files (CRA was transpiling .js as JSX by default)
      include: '**/*.{jsx,js}',
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'build',
    sourcemap: false,
    chunkSizeWarningLimit: 1000,   // suppress 500KB warning (gzip size is what matters, ~137KB is OK)
    rollupOptions: {
      output: {
        manualChunks: {
          vendor:  ['react', 'react-dom', 'react-router-dom'],
          charts:  ['recharts'],
          ui:      ['lucide-react', '@radix-ui/react-dialog', '@radix-ui/react-dropdown-menu',
                    '@radix-ui/react-select', '@radix-ui/react-popover', '@radix-ui/react-tooltip'],
          sonner:  ['sonner'],
        },
      },
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  // Tell esbuild to parse .js files as JSX
  esbuild: {
    loader: 'jsx',
    include: /src\/.*\.[jt]sx?$/,
    exclude: [],
  },
  optimizeDeps: {
    esbuildOptions: {
      loader: {
        '.js': 'jsx',
      },
    },
  },
})
