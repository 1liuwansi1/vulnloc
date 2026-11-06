# Licensing map

Copyright 2026 The vulnloc authors. Individual author names, affiliation, venue
and DOI are explicitly pending and are not invented here. Where a file or
third-party component carries its own notice, that notice controls.

## Apache License 2.0

The following are licensed under the Apache License, Version 2.0 (`LICENSE`):

- offline wrapper source: `src/vulnloc/`
- analysis, verification and candidate-manifest scripts: `scripts/`
- tests: `tests/`
- website source: `site/src/`, `site/scripts/`, `site/tests/`,
  `site/astro.config.mjs`, `site/playwright.config.ts`, `site/package.json`,
  `site/package-lock.json`, and site build configuration
- frozen research implementations and configurations: `experiments/` (their
  historical provenance and any third-party notices remain applicable)
- workflow and build configuration under `.github/`
- executable code snippets embedded in documentation

The Apache license applies to software and executable code. It does not grant
rights to third-party material described in `THIRD_PARTY_NOTICES.md`.

## Creative Commons Attribution 4.0 International

The following are licensed under CC BY 4.0:

- metrics-only derived data: `data/processed/`
- aggregate result files: `results/`
- the S0 Top-5 audit results: `audit/s0_top5_lr/results.json`
- manuscript text, tables, figures and the compiled PDF: `paper/`
- explanatory documentation and website prose: `README.md`, `docs/`,
  `site/*.md`, and the rendered website copy

License text and attribution guidance: `LICENSE-DATA`.

Suggested attribution:

> vulnloc research artifact, The vulnloc authors (individual author list
> pending), 2026. Derived in part from VulnGym v0.1.4 (CC BY 4.0).

## Not distributed

Internal review, remediation, build and publication operational reports at the
repository root (for example `P25_*`, `P26_*`, `OPEN_SOURCE_BUILD_REPORT.md`,
`WEBSITE_BUILD_REPORT.md`, `GITHUB_PUBLICATION_REPORT.md`) are local engineering
records, not part of the published candidate, and are not licensed for
redistribution by this map. The ignored `.local/` working snapshot is private
and must never be published.

## Third-party and excluded material

`THIRD_PARTY_NOTICES.md` describes upstream VulnGym attribution and the excluded
third-party repository source, advisory text, model outputs, embeddings and
indexes. Nothing here re-licenses material the project does not own.
