import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./" so the built files load from pywebview's local server
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { port: 5173, strictPort: true },
  build: { chunkSizeWarningLimit: 2000 },
});
