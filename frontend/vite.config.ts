import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  base: "/ui/",
  build: {
    outDir: "../app/web_dist",
    emptyOutDir: true,
    target: "es2022",
    manifest: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8740",
      "/health": "http://127.0.0.1:8740",
    },
  },
});
