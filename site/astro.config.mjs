import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const siteRoot = fileURLToPath(new URL('.', import.meta.url));
const python = fileURLToPath(new URL('../.venv/bin/python', import.meta.url));
const guard = (script) => execFileSync(python, ['-B', `scripts/${script}.py`], {
  cwd: siteRoot, stdio: 'inherit', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
});
const researchGate = {
  name: 'verified-research-boundary',
  hooks: {
    'astro:build:start': () => { guard('validate_data'); guard('source_boundary'); },
    'astro:build:done': () => guard('scan_dist'),
  },
};

// No invented GitHub identity. Set SITE_URL after human release approval.
export default defineConfig({
  site: process.env.SITE_URL || 'http://localhost:4321',
  base: '/vulnloc',
  trailingSlash: 'always',
  output: 'static',
  i18n: { defaultLocale: 'en', locales: ['en', 'zh'], routing: { prefixDefaultLocale: true, redirectToDefaultLocale: false } },
  integrations: [researchGate, react()],
  vite: { plugins: [tailwindcss()], build: { sourcemap: false } },
  devToolbar: { enabled: false },
});
