import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the UI runs on Vite (port 5173) and forwards /api calls to FastAPI.
// In production FastAPI serves the built files from dist/, so no proxy is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
