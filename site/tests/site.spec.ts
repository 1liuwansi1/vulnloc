import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
const data = JSON.parse(readFileSync(new URL('../src/data/verified.json', import.meta.url), 'utf8'));

const widths = [1920, 1440, 768, 390];
const pages = ['', 'methodology/', 'results/', 'analysis/', 'reproducibility/', 'paper/', 'resources/'];
for (const width of widths) {
  test(`all pages, overflow and console at ${width}px`, async ({ page, baseURL }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on('request', request => {
      if (new URL(request.url()).origin !== new URL(baseURL!).origin) errors.push('Unexpected external request');
    });
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    page.on('response', response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
    for (const route of pages) {
      const response = await page.goto(route ? `/vulnloc/${route}` : '/vulnloc/');
      expect(response?.status()).toBe(200);
      await expect(page.locator('h1')).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      if (route === 'results/') await expect(page.locator('.chart svg').first()).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
      await page.screenshot({ path: testInfo.outputPath(`round2-${width}-${route.replace('/', '') || 'home'}.png`), fullPage: true });
      const links = await page.locator('a[href]').evaluateAll(nodes => nodes.map(node => node.getAttribute('href')!));
      for (const href of links) expect(href.startsWith('/vulnloc/') || href.startsWith('#')).toBeTruthy();
    }
    expect(errors).toEqual([]);
  });
}

test('results switch: all six arms match scientific JSON', async ({ page }) => {
  await page.goto('/vulnloc/results/');
  await expect(page.locator('.chart svg').first()).toBeVisible();
  for (const study of ['s0', 's1'] as const) {
    await page.getByRole('button', { name: study === 's0' ? 'S0 · Confirmatory' : 'S1 · Supplemental' }).click();
    const rows = page.locator('table').first().locator('tbody tr');
    for (const [index, arm] of (['agent', 'rag', 'pack'] as const).entries()) {
      const item = data.studies[study].arms[arm];
      await expect(rows.nth(index)).toContainText((100 * item.file_recall5).toFixed(2) + '%');
      await expect(rows.nth(index)).toContainText((100 * item.line_recall5).toFixed(2) + '%');
      await expect(rows.nth(index)).toContainText(`${item.failures} / ${item.units}`);
    }
    for (const metric of ['LR@5', 'Failures', 'FR@5']) {
      await page.getByRole('button', { name: metric, exact: true }).click();
      await expect(page.getByRole('button', { name: metric, exact: true })).toHaveAttribute('aria-pressed', 'true');
    }
  }
  await expect(page.getByText('−0.0250')).toHaveCount(0); // only display-derived percentage points, not a hardcoded claim
  await expect(page.getByText('-2.50', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('S1 is not independent confirmation.', { exact: false })).toBeVisible();
});

test('method explorer, mobile navigation, clipboard and FAQ', async ({ page, context }) => {
  await page.goto('/vulnloc/methodology/');
  await page.getByRole('button', { name: 'RAG', exact: true }).click();
  await expect(page.getByText('RAG: Single-round hybrid retrieval')).toBeVisible();
  await page.getByRole('button', { name: 'Pack', exact: true }).click();
  await expect(page.getByText('Pack: Lexicographic context packing')).toBeVisible();
  await page.getByRole('button', { name: 'Agent', exact: true }).click();
  await expect(page.getByText('Agent: Read-only adaptive exploration')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Menu' }).click();
  await page.getByRole('link', { name: 'Reproduce', exact: true }).click();
  await expect(page).toHaveURL(/reproducibility/);
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.getByRole('button', { name: 'Copy reproduction commands' }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('.venv/bin/vulnloc verify-results');
  await page.getByText('Can I reproduce the original model answers?', { exact: true }).click();
  await expect(page.getByText('No. L1 reaggregates stored scores.', { exact: false })).toBeVisible();
});

test('reduced motion, keyboard access and subpath assets', async ({ page, request }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/vulnloc/');
  expect(await page.locator('.signal').evaluate(node => getComputedStyle(node).animationName)).toBe('none');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused();
  await page.keyboard.press('Enter');
  const paths = await page.locator('script[src],link[rel="stylesheet"]').evaluateAll(nodes => nodes.map(node => node.getAttribute('src') || node.getAttribute('href')!));
  for (const path of paths) { expect(path).toMatch(/^\/vulnloc\/_astro\//); expect((await request.get(path)).status()).toBe(200); }
  for (const route of pages) expect((await request.get(`/vulnloc/${route}`)).status()).toBe(200);
});
