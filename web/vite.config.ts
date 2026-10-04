import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "DJUtil",
        short_name: "DJUtil",
        description: "Rekordbox library companion",
        theme_color: "#0a0a0b",
        background_color: "#0a0a0b",
        display: "standalone",
        icons: [
          {
            src: "icons/icon-192.png",
            sizes: "192x192",
            type: "image/png",
          },
          {
            src: "icons/icon-512.png",
            sizes: "512x512",
            type: "image/png",
          },
          {
            src: "icons/icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // Never cache API responses offline — except artwork, which is
        // content-addressed and immutable.
        runtimeCaching: [
          {
            urlPattern: /\/api\/artwork\/[0-9a-f]{64}/,
            handler: "CacheFirst",
            options: {
              cacheName: "djutil-artwork",
              expiration: { maxEntries: 2000, maxAgeSeconds: 30 * 24 * 3600 },
            },
          },
          {
            urlPattern: /\/api\/.*/,
            handler: "NetworkOnly",
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});
