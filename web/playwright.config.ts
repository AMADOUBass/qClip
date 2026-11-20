import { defineConfig } from "@playwright/test";

// Tests de bout en bout : l'API (`uv run qclip serve`) et le front (`pnpm dev`) doivent tourner.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: { baseURL: "http://localhost:3000", viewport: { width: 1600, height: 1000 }, locale: "fr-FR" },
  reporter: "list",
});
