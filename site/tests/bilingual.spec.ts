import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
const data = JSON.parse(readFileSync(new URL('../src/data/verified.json', import.meta.url),'utf8'));
const routes = ['', 'methodology/', 'results/', 'analysis/', 'reproducibility/', 'paper/', 'resources/'];

for (const locale of ['en','zh']) for (const width of [1920,1440,768,390]) {
  test(`${locale} complete static pages at ${width}px`, async ({page,baseURL}, testInfo) => {
    await page.setViewportSize({width,height:1000});
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if(message.type()==='error') errors.push(message.text()); });
    page.on('response', response => { if(response.status()>=400) errors.push(String(response.status())); });
    page.on('request', request => { if(new URL(request.url()).origin !== new URL(baseURL!).origin) errors.push('External request'); });
    for (const route of routes) {
      expect((await page.goto(`/vulnloc/${locale}/${route}`))?.status()).toBe(200);
      await expect(page.locator('html')).toHaveAttribute('lang',locale==='zh'?'zh-CN':'en');
      await expect(page.locator('h1')).toBeVisible();
      expect(await page.locator('link[rel=canonical]').getAttribute('href')).toContain(`/vulnloc/${locale}/${route}`);
      expect(await page.locator('link[hreflang=en]').getAttribute('href')).toContain(`/vulnloc/en/${route}`);
      expect(await page.locator('link[hreflang="zh-CN"]').getAttribute('href')).toContain(`/vulnloc/zh/${route}`);
      expect(await page.locator('meta[name=description]').getAttribute('content')).toMatch(locale==='zh'?/[\u4e00-\u9fff]/:/research/i);
      if(route==='results/') await expect(page.locator('.chart svg').first()).toBeVisible();
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();
      await page.screenshot({path:testInfo.outputPath(`${locale}-${width}-${route.replace('/','')||'home'}.png`),fullPage:true});
    }
    expect(errors).toEqual([]);
  });
}

test('language switch retains page, study, metric, hash and preference',async({page})=>{
  await page.goto('/vulnloc/en/results/');
  await expect(page.locator('[data-hydrated="true"]').first()).toBeVisible();
  await page.getByRole('button',{name:'S1 · Supplemental'}).click();
  await page.getByRole('button',{name:'LR@5',exact:true}).click();
  await page.evaluate(()=> { location.hash='main'; });
  await page.locator('.language-switch').click();
  await expect(page).toHaveURL(/\/zh\/results\/\?study=s1&metric=line_recall5#main/);
  await expect(page.getByRole('button',{name:'S1 · 补充研究'})).toHaveAttribute('aria-pressed','true');
  await expect(page.getByRole('button',{name:'LR@5',exact:true})).toHaveAttribute('aria-pressed','true');
  expect(await page.evaluate(()=>localStorage.getItem('vulnloc.locale'))).toBe('zh');
  await expect(page.getByText('行级召回率 LR@5',{exact:true})).toBeVisible();
  await page.goto('/vulnloc/');
  await expect(page).toHaveURL(/\/zh\/$/);
  await page.goto('/vulnloc/zh/methodology/');
  await page.getByRole('button',{name:'RAG',exact:true}).click();
  await page.locator('.language-switch').click();
  await expect(page).toHaveURL(/\/en\/methodology\/\?method=RAG/);
  await expect(page.getByText('RAG: Single-round hybrid retrieval')).toBeVisible();
});

test('both languages show identical scientific numbers for both studies', async({page})=>{
  const numbers: Record<string,string[][]> = {};
  for(const locale of ['en','zh']) for(const study of ['s0','s1']) {
    await page.goto(`/vulnloc/${locale}/results/?study=${study}`);
    await expect(page.locator('[data-hydrated="true"]').first()).toBeVisible();
    await expect(page.locator(`[aria-label="${locale==='en'?'Select study':'选择研究'}"] button`).nth(study==='s0'?0:1)).toHaveAttribute('aria-pressed','true');
    const rows = page.getByTestId('means').locator('tbody tr');
    const actual:string[][]=[];
    for(const [index,arm] of ['agent','rag','pack'].entries()) {
      const cells = await rows.nth(index).locator('td').allTextContents();
      actual.push(cells.slice(1));
      await expect(rows.nth(index)).toContainText((data.studies[study].arms[arm].file_recall5*100).toFixed(2)+'%');
    }
    const contrasts = await page.getByTestId('contrasts').locator('tbody tr').evaluateAll(rows=>rows.map(row=>Array.from(row.querySelectorAll('td')).slice(2).map(cell=>(cell.textContent||'').match(/[+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?/g)?.join('|')||'')));
    numbers[locale+study]=[...actual,...contrasts];
  }
  expect(numbers.ens0).toEqual(numbers.zhs0);
  expect(numbers.ens1).toEqual(numbers.zhs1);
});

test('Chinese browser detection, explicit preference and static fallback',async({browser,baseURL})=>{
  const context=await browser.newContext({locale:'zh-CN',baseURL});
  const page=await context.newPage();
  await page.goto('/vulnloc/');
  await expect(page).toHaveURL(/\/zh\/$/);
  await page.evaluate(()=>localStorage.setItem('vulnloc.locale','en'));
  await page.goto('/vulnloc/');
  await expect(page).toHaveURL(/\/en\/$/);
  await context.close();
  const offline=await browser.newContext({javaScriptEnabled:false,baseURL});
  const staticPage=await offline.newPage();
  await staticPage.goto('/vulnloc/en/paper/');
  await staticPage.locator('.language-switch').click();
  await expect(staticPage).toHaveURL(/\/zh\/paper\/$/);
  await expect(staticPage.locator('html')).toHaveAttribute('lang','zh-CN');
  await offline.close();
});

test('localized copy feedback and mobile language control',async({page,context})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto('/vulnloc/zh/reproducibility/');
  await context.grantPermissions(['clipboard-read','clipboard-write']);
  await page.getByRole('button',{name:'复制复现命令'}).click();
  await expect(page.getByRole('button',{name:'复制复现命令'})).toHaveText('已复制');
  expect(await page.evaluate(()=>navigator.clipboard.readText())).toContain('.venv/bin/vulnloc verify-results');
  await expect(page.locator('.language-switch')).toBeVisible();
  await page.getByRole('button',{name:'菜单'}).click();
  await page.getByRole('link',{name:'实验结果',exact:true}).click();
  await expect(page).toHaveURL(/\/zh\/results\/$/);
});

test('every Chinese method branch and copy-error feedback is localized',async({page})=>{
  await page.goto('/vulnloc/zh/methodology/');
  await expect(page.locator('[data-hydrated="true"]').first()).toBeVisible();
  for(const [name,title] of [['Agent','只读自适应探索智能体'],['RAG','单轮混合检索'],['Pack','词典序上下文打包']]) {
    await page.getByRole('button',{name,exact:true}).click();
    await expect(page.getByText(`${name}: ${title}`,{exact:true})).toBeVisible();
  }
  await page.addInitScript(()=>Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{throw new Error('synthetic browser permission denial');}}}));
  await page.goto('/vulnloc/zh/reproducibility/');
  await page.getByRole('button',{name:'复制复现命令'}).click();
  await expect(page.getByRole('button',{name:'复制复现命令'})).toHaveText('请选中文本复制');
});

test('language navigation works when storage is unavailable',async({page})=>{
  await page.addInitScript(()=>{
    Storage.prototype.setItem=()=>{throw new Error('synthetic storage denial');};
    Storage.prototype.getItem=()=>{throw new Error('synthetic storage denial');};
  });
  await page.goto('/vulnloc/en/results/?study=s1&metric=failures');
  await page.locator('.language-switch').click();
  await expect(page).toHaveURL(/\/zh\/results\/\?study=s1&metric=failures/);
  await expect(page.getByRole('button',{name:'失败次数',exact:true})).toHaveAttribute('aria-pressed','true');
});
