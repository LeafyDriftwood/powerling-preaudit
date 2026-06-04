import type { NextConfig } from "next";

const requiredEnvVars = [
  'SESSION_SECRET',
  'SSO_HOST',
  'SSO_SERVICE_KEY',
  'APP_HOST',
  'NEXT_PUBLIC_APP_URL',
  'JWT_SECRET',
];

for (const key of requiredEnvVars) {
  if (!process.env[key]) {
    throw new Error(`Missing required environment variable: ${key}`);
  }
}

const nextConfig: NextConfig = {};

export default nextConfig;
