import type { NextConfig } from "next";

const isProd = process.env.NODE_ENV === "production";
// The backend origin the browser is allowed to call (see lib/api.ts). Falls back to
// the same localhost default used there so local dev keeps working unconfigured.
const apiOrigin = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// This app is fully self-hosted: no external fonts/CDN/analytics scripts are loaded
// anywhere (verified against app/ and lib/), so the policy below can be narrow except
// for one unavoidable exception: Next.js's App Router injects its own inline hydration
// bootstrap scripts on every page (confirmed by testing 'self'-only in production --
// the app fails to hydrate at all without 'unsafe-inline' here). Next.js does support
// a nonce-based strict CSP, but that requires per-request nonce middleware wired through
// the root layout; given this app already has its own auth middleware.ts, that is a
// larger, riskier change than this hardening pass should make. 'unsafe-inline' is the
// documented, safe middle ground here. Dev mode (HMR) additionally needs 'unsafe-eval'.
const scriptSrc = isProd ? "'self' 'unsafe-inline'" : "'self' 'unsafe-inline' 'unsafe-eval'";
const csp = [
  "default-src 'self'",
  `script-src ${scriptSrc}`,
  // 'unsafe-inline' is required for style-src: framer-motion (used throughout the
  // shop-floor UI for transitions) applies inline style="" attributes at runtime.
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Content-Security-Policy", value: csp },
  // Only meaningful once HTTPS is guaranteed in front of this app in production --
  // see docs/PRODUCTION_DEPLOYMENT.md. Never sent in local HTTP development.
  ...(isProd ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }] : []),
];

const nextConfig: NextConfig = {
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: false,
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
