import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const logoFileName = 'logo.webp'
const logoSourcePath = resolve(__dirname, '..', logoFileName)

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
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/fonts': 'http://127.0.0.1:8000'
    }
  }
})
