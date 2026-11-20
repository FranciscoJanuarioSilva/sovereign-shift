import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// frontend/serve.py serves the build from frontend/dist: npm run build, then run serve.py
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../dist", emptyOutDir: true },
});
