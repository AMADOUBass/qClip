import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  agentRules: false, // pas de AGENTS.md généré : les consignes du projet sont dans ../CLAUDE.md
  devIndicators: { position: "bottom-right" }, // en bas à gauche, il cachait la jauge CPU de la barre latérale
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
