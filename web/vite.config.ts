import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The production build is written into the Python package, so `greenbench serve` ships the UI.
// `--mode pages` builds the static GitHub Pages copy instead (see scripts/deploy-pages.mjs).
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  build: {
    outDir: mode === "pages" ? "dist-pages" : "../src/greenbench/server/static",
    emptyOutDir: false, // emptied by scripts/clean-static.mjs (fs.rmSync is unreliable on non-ASCII paths)
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
}));
