import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const logoFileName = 'logo.webp'
const logoSourcePath = fileURLToPath(new URL('../logo.webp', import.meta.url))
const apiTarget = process.env.CATLABEL_DEV_API_URL || 'http://127.0.0.1:8000'

const getLogoContents = () => {
  if (!existsSync(logoSourcePath)) {
    throw new Error(`Expected app logo at ${logoSourcePath}`)
  }

  return readFileSync(logoSourcePath)
}

const rootLogoAsset = () => ({
  name: 'catlabel-root-logo-asset',
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      const requestPath = (req.url || '').split('?')[0]
      if (requestPath !== `/${logoFileName}`) {
        return next()
      }

      try {
        res.setHeader('Content-Type', 'image/webp')
        res.end(getLogoContents())
      } catch (error) {
        next(error)
      }
    })
  },
  generateBundle() {
    this.emitFile({
      type: 'asset',
      fileName: logoFileName,
      source: getLogoContents()
    })
  }
})

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), rootLogoAsset()],
  test: {
    environment: 'jsdom',
    restoreMocks: true
  },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          includeDependenciesRecursively: false,
          groups: [
            { name: 'react-vendor', test: /[\\/]node_modules[\\/](react|react-dom|scheduler|use-sync-external-store)[\\/]/ },
            { name: 'canvas-vendor', test: /[\\/]node_modules[\\/](konva|react-konva|react-reconciler|its-fine)[\\/]/ },
            { name: 'editor-vendor', test: /[\\/]node_modules[\\/](zustand|dompurify|html-to-image)[\\/]/ }
          ]
        }
      }
    }
  },
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: {
      '/api': apiTarget,
      '/fonts': apiTarget
    }
  }
})
