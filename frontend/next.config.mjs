import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  agentRules: false,
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  distDir: process.env.NEXT_DIST_DIR || ".next",
  turbopack: {
    root: projectRoot,
  },
};

export default nextConfig;
