import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: { baseURL: process.env.PREVIEW_URL || 'http://127.0.0.1:4321/vulnloc/', browserName: 'chromium' },
  reporter: 'list',
});
