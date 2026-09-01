import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: './' — относительные пути, чтобы работать на project-Pages
// (https://user.github.io/repo/) без знания имени репозитория. Навигация — вкладками
// в состоянии приложения, без роутера, поэтому глубокие ссылки не зависят от base.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
});
