import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const proxyTarget = process.env.VITE_PROXY_TARGET ?? "http://localhost:8001";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/graphql": { target: proxyTarget, changeOrigin: true },
      "/healthz": { target: proxyTarget, changeOrigin: true },
    },
  },
});
