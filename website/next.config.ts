import type { NextConfig } from "next";

// GitHub Pages serves the site under /<repo>; set NEXT_PUBLIC_BASE_PATH=/AgentCrucible in that build.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig: NextConfig = {
  output: "export",
  basePath,
  trailingSlash: true,
  images: { unoptimized: true },
  // cacheComponents / partialPrefetching (PPR) are not supported with `output: "export"`.
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
