import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  root: path.resolve(__dirname),
  // The public deployment is served as a same-origin SPA. Absolute asset URLs
  // keep the Workbench usable after a browser refresh on a nested URL.
  base: process.env.VITE_PUBLIC_DEMO === "true" ? "/" : "./",
  server: {
    proxy: {
      "/api": {
        target: process.env.WORKBENCH_API_ORIGIN ?? "http://127.0.0.1:8000",
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: path.resolve(__dirname, "../dist-workbench"),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("recharts") || id.includes("d3-")) return "charts";
          if (id.includes("@tanstack") || id.includes("zustand")) return "state";
          if (id.includes("react") || id.includes("lucide-react")) return "react-vendor";
          return undefined;
        }
      }
    }
  }
});
