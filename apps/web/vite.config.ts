import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
  test: {
    environment: "jsdom",
    pool: "threads",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    css: true,
  },
});
