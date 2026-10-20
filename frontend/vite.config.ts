import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

// 開發時把 /api 轉給本機後端，前端程式碼不必知道後端網址。
// 正式環境由 docker/nginx.conf 做同樣的轉發。
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: loadEnv(mode, ".", "API_PROXY_").API_PROXY_TARGET || "http://localhost:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
}));
