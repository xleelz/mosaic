import type { NextConfig } from "next";

// The browser calls /api/mosaic/v1/...; the route handler in
// src/app/api/mosaic/[...path]/route.ts proxies it to mosaicd, reading
// MOSAIC_SERVER and MOSAIC_TOKEN from the server environment at request time.

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  reactStrictMode: true,
  poweredByHeader: false,
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
