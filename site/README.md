# vulnloc research website

Seven shared pages in English and Simplified Chinese, with two React islands for method and result
exploration. The site is part of the published research artifact: code is
Apache-2.0; metrics-only data, manuscript and figures are CC BY 4.0; individual
authors, affiliation, venue and DOI remain PENDING.

Live: https://1liuwansi1.github.io/vulnloc/  
English: https://1liuwansi1.github.io/vulnloc/en/  
中文: https://1liuwansi1.github.io/vulnloc/zh/

## Local commands (WSL)

The research checkout must already have its Python 3.12 environment installed.
The website uses Node 22.23.4 locally (installed by npm as a dev tool), Astro 7,
React 19, ECharts 6, TypeScript and Tailwind 4 through its Vite plugin.

```bash
cd /path/to/vulnloc/site
npm ci
npm run dev                         # WSL / Windows: http://localhost:4321/vulnloc/

npm run check                      # Astro + TypeScript
npm run build                      # verified data → static pages → dist scan
npm run preview -- --port 4321      # verify again, scan, serve the built site
npm run validate:data
npm run test:security
npx playwright install chromium    # first-time browser install
npm run test:browser                # preview must be running
```

Scripts are intended for Linux/WSL.
For bootstrap, a system Node >=22.23.4 is recommended. This machine's original
22.23.2 emits npm engine warnings during installation; `npm ci` succeeds and
the npm scripts then use the lockfile-installed Node 22.23.4. Do not bypass
Astro's runtime engine requirement with the older system interpreter.

Runtime Python is used only as a verifier;
the environment directory is never a website data source or public asset.
Installation downloads frontend packages; reproduction and site rendering do
not call model APIs. Astro telemetry is disabled in the supported npm scripts.

Astro 7 preview runs a local daemon. Use `npx astro preview status` and
`npx astro preview stop` if needed. Do not run dev and preview on the same port.
The running preview can be reached in a Windows browser through WSL localhost
forwarding; if your WSL firewall policy prevents that, use the local WSL IPv4
and port shown by the server. Nothing has been exposed through a public tunnel.

## Data flow and safety

1. `scripts/validate_data.py` runs the research CLI's `verify` and
   `verify-results` without rewriting scientific outputs.
2. It checks exact input-hash closure, both per-study CSVs and statistics, and
   independently recomputes the supported frozen contrasts from stored scores.
3. Only allowlisted aggregate fields become `src/data/verified.json`. That file
   is generated/ignored; there is no fallback, case text, raw output, entry ID,
   or private provenance path in the client payload.
4. `scripts/source_boundary.py` checks source imports, symlinks and the empty
   public asset boundary. No research directory is a Vite asset alias.
   CSS URL loads and escaped CSS imports are rejected before Vite can inline
   content and erase its private source path.
5. Build hooks enforce the same checks even for direct `astro build`.
6. `scripts/scan_dist.py` scans actual output, including decoded path/secret
   shapes. Only route HTML, hashed JavaScript/CSS, and empty `.nojekyll` are
   accepted. PDFs, archives, maps, JSON data dumps and unapproved files fail.

`public/` is deliberately empty except `.nojekyll`. No paper PDFs, third-party
source, experimental trajectories, repository caches, embeddings or indexes
are copied. The lack of an approved real case is handled with a method explorer,
explicitly an illustration of policy definitions, not a fabricated trace.

Displayed experimental values derive from verified JSON. Bars share fixed
zero-origin scales. Error bars show **paired contrast** CIs, not invented
arm-level uncertainty. Repeats are averaged within entry; inference has n=80.
The statistical seed and the historical S0 p-rounding warning remain visible.

## Scope

- L1 stored-score aggregation/inference: implemented.
- L2 raw-dependent figure regeneration: incomplete.
- L3 online collection: incomplete; no provider integration in the site.
- Manuscript: CC BY 4.0 in the repository; the site provides an explicitly
  paraphrased synopsis rather than copying the PDF. Individual authors and DOI
  remain PENDING.
- S0/S1 are separate configurations on the same known entries; no causal
  S0–S1 interpretation, pooled inference or universal Agent claim is made.

## Bilingual routes

English: `/vulnloc/en/`; Simplified Chinese: `/vulnloc/zh/`. Every page has the
same suffix in both languages. The root considers explicit `vulnloc.locale`
localStorage preference, then the browser language, otherwise English. Explicit
locale URLs are never forcibly redirected by a stored preference. Static
language links work without JavaScript; JavaScript additionally preserves query
selection, hash and scroll, and stores an explicit choice. Navigation uses real
static documents, not a new SPA or an online translation API.

`src/i18n/zh.ts` contains type-safe source-message translations;
`src/i18n/content.ts` maintains long-form editorial resources. Shared templates
are in `src/views/`. Both locales import the same `verified.json` and use the
same `Intl` number-formatting policy; code/commands/model names are unchanged.
Canonical, language and hreflang metadata are localized. Old P3 page paths
remain available as English-compatible bookmarks with locale canonical URLs.

See `DEPLOYMENT.md` for project-subpath hosting and the release record. The
workflow requires both the repository approval variable and exact-candidate (or
explicitly approved continuous-baseline) human approvals. The live URL and
Actions status are recorded in the local publication report.
The P26 repository-level publication/hash
inventories are historical snapshots; do not treat them as a current website
release manifest. Generate a new approved release inventory only after review.
