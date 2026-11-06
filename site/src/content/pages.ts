export type ContentPage = {
  eyebrow: string;
  title: string;
  intro: string;
  sections: { title: string; body: string[]; items?: string[] }[];
};

// Editorial paraphrases of the cited checkout documents; no raw case content.
export const content: Record<'analysis' | 'reproducibility' | 'paper' | 'resources', ContentPage> = {
  analysis: {
    eyebrow: 'Reading the evidence',
    title: 'Acquisition is not the same as reliable localization',
    intro: 'The study separates which source is available, which source reaches the model, what locations it returns, and whether its final output is usable. No single recall score captures all four.',
    sections: [
      {
        title: 'What FR@5 and LR@5 measure',
        body: [
          'FR@5 measures coverage of the one or two unique annotated entry-point (EP) and critical-operation (CO) file paths among the top five predictions. It is recall, not precision, and the reported mean is entry-weighted rather than pooled over target files.',
          'LR@5 retains two annotation opportunities even when EP and CO share a file. A same-file predicted interval receives credit for overlap with five-line tolerance. It does not require exact lines, narrow intervals, correct explanations, or exploit validation; broad intervals can earn credit.',
          'Empty or invalid final outputs receive zero for both metrics and remain in every reported denominator. S0’s parser already limited predictions to five: the audited absence of a second slice in its LR function changes none of its 720 scores.',
        ],
      },
      {
        title: 'Acquisition, interval extent, and completion',
        body: [
          'Shared source eligibility does not guarantee source delivery, and delivery does not establish that the model used the evidence. The paper examines these distinctions using historical diagnostics; the L1 website does not regenerate or chart those raw-dependent measurements.',
          'A tolerance-based interval hit does not by itself demonstrate acquisition of the corresponding source. Wide intervals may receive credit. The stored metrics cannot identify whether titles, other source, or model knowledge produced a hit.',
          'Output failures are reported alongside recall in the results explorer. Excluding failed outputs would change the comparison population. Associations discussed in the manuscript do not prove a cause or estimate the performance of a repaired system.',
        ],
      },
      {
        title: 'Paired inference, not 240 independent samples',
        body: [
          'Each study contains 80 entries × three arms × three repeats. Repeats are averaged within each entry before paired comparisons, so the entry-level analysis has n = 80. S0 and S1 are reported separately, never pooled.',
          'The frozen primary contrast is Agent–Pack FR@5. Four secondary contrasts compare Agent–RAG and RAG–Pack for file and interval recall, with Benjamini–Hochberg adjustment at q = 0.10. The frozen procedures use 100,000 Monte Carlo sign-flip draws and 10,000 bootstrap draws; S0 and S1 retain their distinct numerical implementations.',
          'The 13 repository groups are imbalanced, with 45 of 80 entries from one repository. Entry independence is an assumption. Manuscript repository-sensitivity diagnostics do not certify independence or supply a general cluster-robust estimator. S1 does not establish an Agent advantage over RAG in file recall.',
        ],
      },
      {
        title: 'Limits of the comparison',
        body: [
          'Both studies use the recorded DeepSeek V4 Pro / high setting and the same known sample. S1 bundles multiple implementation changes after S0 was observed; differences between studies cannot isolate any one change.',
          'Dataset-supplied titles may contain target filenames. Description-only NO_PATH_HINT labels are not evidence of clue-free inputs. Pack is a weak lexical reference, and the common 50,000-token repository-information ceiling does not equalize cumulative model input, compute, fees, or latency.',
          'Sources: docs/METHODS.md; paper/sections/03_methodology.tex through 07_threats_to_validity.tex; paper/main.tex.',
        ],
      },
    ],
  },
  reproducibility: {
    eyebrow: 'Artifact boundaries',
    title: 'Reproduce the stored-score analysis offline',
    intro: 'The implemented L1 workflow validates and reaggregates stored metrics. It makes no model calls and requires no API key; it is not an independent rescoring of raw predictions or a new experiment.',
    sections: [
      {
        title: 'What L1 verifies',
        body: [
          'Validation checks hashes, 720 unique scheduled units per study, 80 entries, the allowed score schema, and zero scores for failed outputs. Reproduction compares all five frozen contrasts, official numerical references, and the supported manuscript table and contrast values.',
          'S0 metrics are a packaging-time derivative of the independent audit CSV, verified row by row against raw records and the frozen scorer during packaging. S1 also matches the official per-record scores. The distributed metrics-only data cannot independently reassess labels or prediction text.',
        ],
      },
      {
        title: 'Environment and generated outputs',
        body: [
          'Python 3.12 is the validated interpreter. NumPy 2.5.3 is pinned to preserve historical S1 numerical and random-number behavior. Dependency installation may require network access; the analysis itself is offline and needs no model SDK.',
          'The all-studies reproduction produces the combined six-row results/main_results.json, CSV, and Markdown table. A single-study run updates its own tables and statistics without rewriting the combined table. The site’s data contract requires verify-results to reject missing, duplicate, tampered, or non-finite data.',
          'Per-study statistics record input hashes, analysis seeds, and Python/NumPy versions. These are engineering-derived L1 provenance records, not a substitute for historical raw provenance.',
        ],
      },
      {
        title: 'What remains incomplete',
        body: [
          'L2 raw-dependent figure regeneration is incomplete. Included manuscript figures are saved assets, not newly regenerated outputs. Source-delivery, interval-width, and provider-input figures depend on excluded raw records or third-party assets.',
          'The public wrapper does not implement supported online collection. Historical runners depend on private assets and historical launch contracts and can incur charges: inspect them, but do not run them from this artifact. No future provider can be assumed to reproduce the historical responses.',
          'A manuscript build, when its TeX dependencies are available, compiles the included snapshot without overwriting the saved PDF. It does not regenerate figures or revalidate every paper claim.',
        ],
      },
      {
        title: 'Data and release safeguards',
        body: [
          'Raw answers, prompts, thinking, tool results, advisory text, repository checkouts, embeddings, indexes, and model-event logs are excluded. The website should consume only validated L1 result outputs, not private local assets or caches.',
          'This is a published research artifact under the stated licenses: Apache-2.0 for code, CC BY 4.0 for metrics-only data, manuscript and figures. Individual authorship, affiliation, venue and DOI remain PENDING. Do not upload the working directory wholesale; its ignored local snapshot is private and is not a verified independent raw-data backup.',
          'Sources: docs/REPRODUCIBILITY.md; docs/DATA_CARD.md; docs/INSTALL.md; README.md.',
        ],
      },
    ],
  },
  paper: {
    eyebrow: 'Manuscript snapshot',
    title: 'Evidence Acquisition and Output Reliability for Advisory-Guided Vulnerability Localization',
    intro: 'A same-model comparison of read-only adaptive exploration, single-round hybrid retrieval, and lexicographic packing under a repository-information ceiling.',
    sections: [
      {
        title: 'Abstract synopsis — paraphrase, not the original abstract',
        body: [
          'Two separately reported studies evaluate the same known VulnGym entries using DeepSeek V4 Pro. Inputs include dataset-supplied titles, which may contain target filenames. The shared 50,000-token ceiling bounds repository-information acquisition rather than all model input.',
          'In the supplemental study, adaptive exploration delivers substantially more annotated source than retrieval but has lower mean file recall. Its retained output failures materially affect this comparison. Retrieval’s tolerant interval hits without corresponding source often depend on wide predicted ranges, while syntactically valid answers can still contain nonexistent paths or out-of-bounds coordinates.',
          'Exploration returns narrower intervals and higher tolerance-based interval recall, with inferential support sensitive to repository dependence, and uses much more cumulative provider input. The paper argues for reporting source delivery, annotation coverage, interval extent, and output validity together rather than treating recall alone as a general ranking of acquisition policies.',
        ],
      },
      {
        title: 'Study design and scope',
        body: [
          'S0 is the original confirmatory comparison. S1 was frozen before its own formal collection but after S0 results and implementation issues were known. It changes authorization, indexing, interaction, parsing, presentation, scheduling, and timing together. It is a supplemental comparison on known entries, not independent confirmation or a single-factor ablation.',
          'The task predicts likely vulnerable locations from a supplied advisory and pinned repository. It does not evaluate unknown-bug discovery, exploitation, patch generation, or a commercial vulnerability scanner. Static-guided retrieval is not implemented.',
        ],
      },
      {
        title: 'Research contributions',
        body: ['The manuscript contributes an empirical characterization of what aggregate localization recall leaves unresolved, rather than a claim of universal Agent superiority.'],
        items: [
          'A separately reported comparison of three implemented context-acquisition configurations on the recorded title-assisted localization task.',
          'A joint interpretation of source availability, annotation roles, predicted interval extent, and output validity.',
          'Complete-denominator analysis that retains failed outputs and distinguishes schema acceptance from repository-valid locations.',
        ],
      },
      {
        title: 'Reading the included snapshot',
        body: [
          'The manuscript source, tables, and saved figures are included in paper/. L1 regenerates the main statistical results, not every raw-dependent figure or diagnostic. The included manuscript discusses historical records that are not all distributed in this artifact.',
          'Individual authors, institutions, venue, and DOI remain PENDING. CITATION.cff records the repository citation without inventing attribution. This page provides an editorial synopsis rather than reproducing the PDF or assigning unconfirmed authorship.',
          'Sources: paper/main.tex; paper/sections/03_methodology.tex; paper/sections/04_experimental_setup.tex; paper/sections/06_analysis_discussion.tex; docs/REPRODUCIBILITY.md.',
        ],
      },
    ],
  },
  resources: {
    eyebrow: 'Source guide',
    title: 'Navigate the research artifact',
    intro: 'These are paths in the local candidate checkout, not promises of a public download, a licensed data release, or a supported online service.',
    sections: [
      {
        title: 'Start with the documented boundaries',
        body: ['The overview, methods, and data card define what is measured, what is distributed, and which claims the artifact can reproduce.'],
        items: [
          'README.md — study overview, result summary, limitations, and release status.',
          'docs/METHODS.md — metric definitions, statistical units, frozen numerical implementations, and the S0 Top-5 implementation audit.',
          'docs/DATA_CARD.md — metrics-only schema, extraction provenance, and excluded content.',
          'docs/REPRODUCIBILITY.md and docs/INSTALL.md — offline workflow, environment, and incomplete reproduction levels.',
        ],
      },
      {
        title: 'Inspect methods and results',
        body: ['Frozen scientific source is retained for inspection, not as a portable paid-model entrypoint. The offline wrapper validates stored metrics without modifying those historical methods.'],
        items: [
          'experiments/s0_frozen/ and experiments/s1_frozen/ — frozen code, configurations, selected protocol documents, and source hashes.',
          'data/processed/ — minimal entry metadata, schedules, metrics-only records, and official references.',
          'results/main_results.json — validated six-row website interface, with separate S0/S1 metadata.',
          'results/s0_statistics.json and results/s1_statistics.json — regenerated frozen contrasts, uncertainty, and input hashes.',
          'docs/provenance/ — source hashes, extraction checks, mappings, and integrity records.',
        ],
      },
      {
        title: 'Manuscript and attribution',
        body: [
          'paper/main.tex and paper/sections/ contain the manuscript snapshot; paper/tables/ and paper/figures/ contain its supporting assets. paper/ARTIFACT_GUIDE.md explains the candidate’s narrower offline scope. Included figures should not be described as newly regenerated.',
          'CITATION.cff records the repository citation while individual authors, affiliation, venue and DOI remain PENDING. LICENSE assigns Apache-2.0 to code; LICENSE-DATA assigns CC BY 4.0 to metrics-only data, manuscript and figures. LICENSING.md maps the scope, and THIRD_PARTY_NOTICES.md records upstream attribution and exclusions.',
        ],
      },
      {
        title: 'Release and stewardship',
        body: [
          'Consult docs/RELEASE_CHECKLIST.md and SECURITY.md. The release record documents owner authorization, the selected licenses, PENDING attribution and disclosed residual risks. Preserve private research originals separately and publish only reviewed candidate files.',
          'Sources: README.md; docs/DATA_CARD.md; docs/REPRODUCIBILITY.md; docs/RELEASE_CHECKLIST.md; paper/ARTIFACT_GUIDE.md.',
        ],
      },
    ],
  },
};
