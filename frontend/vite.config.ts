import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const ANALYTICS_BLOCK = /[ \t]*<!-- analytics:start -->[\s\S]*?<!-- analytics:end -->\n?/;

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, "..", "");
  const proxyTarget = env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";

  // Canonical, Open Graph, and structured-data URLs must be absolute, so
  // index.html carries a %SITE_URL% placeholder that is filled in here. Set
  // VITE_SITE_URL to the origin that actually serves the site: pointing the
  // canonical link at a hostname that does not resolve keeps the page out of
  // search results entirely.
  const siteUrl = (env.VITE_SITE_URL || "https://billgitboard.online").replace(/\/+$/, "");

  // Google Analytics measurement ID. Empty by default and empty in every fork:
  // a tag is only emitted when VITE_GA_MEASUREMENT_ID is set at build time, so
  // nobody can accidentally report page views into someone else's property. The
  // dev server never injects it either, so local work stays out of the data.
  const analyticsId = env.VITE_GA_MEASUREMENT_ID ?? "";
  const injectAnalytics = command === "build" && analyticsId !== "";

  // robots.txt and sitemap.xml are generated rather than kept in public/,
  // because both need the absolute origin and files in public/ are copied
  // through untouched. Generating them keeps one source of truth for the URL.
  const sitemap = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    "  <url>",
    `    <loc>${siteUrl}/</loc>`,
    `    <lastmod>${new Date().toISOString().slice(0, 10)}</lastmod>`,
    "    <changefreq>monthly</changefreq>",
    "    <priority>1.0</priority>",
    "  </url>",
    "</urlset>",
    "",
  ].join("\n");

  const robots = [
    "# BillGitBoard",
    "",
    "User-agent: *",
    "Allow: /",
    "",
    "# Job media is user-uploaded and expires; the API is not a page.",
    "Disallow: /api/",
    "Disallow: /media/",
    "",
    `Sitemap: ${siteUrl}/sitemap.xml`,
    "",
  ].join("\n");

  const generated: Record<string, string> = {
    "/robots.txt": robots,
    "/sitemap.xml": sitemap,
  };

  return {
    plugins: [
      react(),
      {
        name: "billgitboard-html-env",
        transformIndexHtml: {
          order: "pre" as const,
          handler: (html: string) => {
            const withUrls = html.split("%SITE_URL%").join(siteUrl);
            return injectAnalytics
              ? withUrls.split("%GA_MEASUREMENT_ID%").join(analyticsId)
              : withUrls.replace(ANALYTICS_BLOCK, "");
          },
        },
        generateBundle() {
          this.emitFile({ type: "asset", fileName: "robots.txt", source: robots });
          this.emitFile({ type: "asset", fileName: "sitemap.xml", source: sitemap });
        },
        // Serve the same two files in development so what you test locally is
        // what deploys.
        configureServer(server) {
          server.middlewares.use((request, response, next) => {
            // @types/node is not in this config's type roots, so read the path
            // off a narrow local view of the request.
            const path = ((request as { url?: string }).url ?? "").split("?")[0];
            const body = generated[path];
            if (body === undefined) {
              next();
              return;
            }
            response.setHeader(
              "Content-Type",
              path === "/sitemap.xml" ? "application/xml" : "text/plain",
            );
            response.end(body);
          });
        },
      },
    ],
    envDir: "..",
    build: {
      outDir: "dist",
      emptyOutDir: true,
    },
    server: {
      host: true,
      port: 5173,
      proxy: {
        "/api": { target: proxyTarget, changeOrigin: true },
        "/media": { target: proxyTarget, changeOrigin: true },
      },
    },
    test: {
      environment: "node",
    },
  };
});
