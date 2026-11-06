# Bilingual GitHub Pages — deployed

Live: https://1liuwansi1.github.io/vulnloc/  
English: https://1liuwansi1.github.io/vulnloc/en/  
中文: https://1liuwansi1.github.io/vulnloc/zh/

The static project base is `/vulnloc/`. English routes are `/en/`, Chinese
routes `/zh/`; root language preference uses explicit localStorage choice,
browser language, then English. Old P3 paths retain English-compatible pages.
All routes have physical `index.html` files; no backend/SPA rewrite is needed.

## Local review

```bash
cd /path/to/vulnloc/site
npm ci
npm run check
npm run test:security
npm run build
npm run preview -- --port 4321
# another terminal
npm run test:browser
```

Preview: `http://localhost:4321/vulnloc/en/` and `/vulnloc/zh/`.
`PREVIEW_URL` can point the browser suite at a separate plain static host with
the reviewed distribution at a physical `vulnloc/` directory.

## Release approval recorded

The project owner authorized publication on 2026-11-06. Code is Apache-2.0;
metrics-only data, manuscript and figures are CC BY 4.0; individual authors,
affiliation, venue and DOI remain PENDING. The approval sidecar binds the
candidate and records the independent raw-backup residual risk rather than
claiming an unperformed verification.

```bash
cd /path/to/vulnloc
python3 -B scripts/prepare_publication_manifest.py --output /tmp/candidate-manifest.json \
  --protected-output /tmp/protected-inputs.json
python3 -B scripts/check_publication_approval.py
```

The manifest selects reviewed candidate files via an explicit root/path
allowlist, rejects selected private/cache/symlink files, excludes internal
reports, and records SHA256. It neither stages files nor uploads anything.
The approval sidecar is excluded from its own digest to avoid self-reference;
it must be reviewed separately. The historical P26 publication inventory is
not used as a current authorization record. Before any future commit, use the
reviewed manifest file list plus the approval sidecar—not `git add .`—and
compare the actual Git index against that list. Unrelated same-name remote
repositories must never be overwritten.

For explicitly approved ongoing main-branch deployment,
`continuous_deployment_approved` and `protected_inputs_sha256` record a separate
scientific/legal baseline (exportable with `--protected-output`). Ordinary
site-only changes can then build and deploy automatically without updating the
initial candidate digest or manually uploading files. Data, frozen code,
scientific wrappers, manuscript, runtime and legal/citation changes still fail
and require renewed review. This ongoing scope is **true** for the approved release.

## Prepared Actions configuration

`.github/workflows/deploy.yml` handles main pushes and manual dispatch, but both
jobs are skipped unless the repository variable `PUBLIC_RELEASE_APPROVED` is
exactly `true`. The build also checks committed human approvals, the unresolved
checklist and the exact initial candidate (or explicitly approved continuous
scientific/legal baseline). A variable alone cannot bypass them.

On approved main pushes, the workflow will:

1. Checkout without persisted credentials; enforce the approval sidecar.
2. Set up Python 3.12.3 and Node 22.23.4; install the scientific package in a
   fresh environment and frontend dependencies with `npm ci`.
3. Run freeze/result verification, scientific tests and candidate screening.
4. Validate site provenance, typecheck, test negative safety cases and audit dependencies.
5. Build both locales and scan actual `site/dist/`.
6. Run the real browser regression suite against the built local preview.
7. Configure Pages, upload **only `site/dist/`**, and deploy through the
   protected `github-pages` environment with Pages/OIDC permissions.

The host uses `github.repository_owner`, not a fabricated username. A real
account must be obtained from `gh auth status` / `gh api user` after normal
interactive authentication. Never paste tokens into the source or chat.

The Python patch is fixed because current stored provenance binds 3.12.3.
Moving to a newer runtime needs explicit compatibility verification; do not
silently relax provenance checks. External Actions execution and live Pages
verification are recorded in the local publication report; a successful Push is
not proof of a live website.

## Pages setup

- The approved owner is `1liuwansi1` and the repository is `1liuwansi1/vulnloc`.
- Enable Pages with **GitHub Actions** as the source.
- Set repository variable `PUBLIC_RELEASE_APPROVED=true` only after the
  committed approval sidecar and protected-input baseline pass.
- Protect the `github-pages` environment with the required human reviewer.
- Verify the completed Actions run and the actual `/en/` and `/zh/` URLs after
  deployment.

No unreviewed directory or raw research data is uploaded; the artifact is only
`site/dist`.
