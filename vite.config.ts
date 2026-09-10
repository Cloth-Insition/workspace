import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      ignored: [
        resolve(__dirname, "src-tauri") + "/**",
        "**/src-tauri/**",
        "**/target/**",
      ],
    },
  },
});