import { useId } from 'react';
import { t, translate, type Locale } from '../i18n';
import { useQueryState } from './useQueryState';

type Method = 'Agent' | 'RAG' | 'Pack';

const methods: Record<Method, { summary: string; access: string; acquisition: string }> = {
  Agent: {
    summary: 'Read-only adaptive exploration',
    access: 'The model can list directories, search with grep, and read authorized source. No shell execution, editing, or general-purpose tools are exposed.',
    acquisition: 'Choose the next action from the advisory and earlier results. S1 permits up to 40 accepted bridge actions and 46 provider requests; rejected tool arguments are not bridge actions.',
  },
  RAG: {
    summary: 'Single-round hybrid retrieval',
    access: 'Index every nonblank eligible source file in 60-line windows with 15-line overlap. Combine BM25 with BAAI/bge-small-en-v1.5 dense retrieval.',
    acquisition: 'Use the supplied title and truncated description as one query. Fuse complete sparse and dense rankings with reciprocal rank fusion (k = 60), then deliver ranked, numbered chunks within the ledger ceiling.',
  },
  Pack: {
    summary: 'Lexicographic context packing',
    access: 'Use the same authorized source manifest, but do not use the advisory to select context. Order repository-relative paths lexicographically.',
    acquisition: 'Spend at most 5,000 accounting tokens on the eligible path list, then append numbered source in lexical file order, retaining complete lines within the remaining ceiling. This is a simple prefix reference, not a strong packing baseline.',
  },
};

export function MethodExplorer({ locale = 'en' }: { locale?: Locale }) {
  const [selected, setSelected] = useQueryState<Method>('method', ['Agent','RAG','Pack'], 'Agent');
  const tr = (key: Parameters<typeof t>[1]) => t(locale,key);
  const text = (value: string) => translate(locale,value);
  const id = useId();
  const method = methods[selected];
  const steps = [
    {
      title: 'Input',
      text: 'Dataset-supplied entry title, public advisory description capped at 1,500 characters, repository URL, and pinned vulnerable commit. Explicit entry-point / critical-operation labels are evaluation-only; supplied titles can still contain filename hints.',
    },
    { title: 'Access', text: method.access },
    { title: 'Acquisition', text: method.acquisition },
    {
      title: 'Output',
      text: 'Return at most five repository-relative file paths with line intervals and brief reasons. S1 requires positive integer intervals; nonempty invalid text gets at most one formatting correction, while empty text fails directly. Output failures score zero and stay in the denominator.',
    },
  ];

  return (
    <section className="method-explorer" aria-labelledby={`${id}-title`}>
      <p className="eyebrow">{tr('Acquisition policies')}</p>
      <h2 id={`${id}-title`}>{tr('Three ways to acquire repository evidence')}</h2>
      <p className="muted">{tr('Illustrative method definitions using the S1 configuration—not a replay of a real case or a live model run.')}</p>
      <div className="tabs" role="group" aria-label={tr('Choose an acquisition method')}>
        {(Object.keys(methods) as Method[]).map((name) => (
          <button
            key={name}
            type="button"
            className={selected === name ? 'active' : undefined}
            aria-pressed={selected === name}
            aria-controls={`${id}-flow`}
            onClick={() => setSelected(name)}
          >
            {name}
          </button>
        ))}
      </div>
      <div id={`${id}-flow`} role="region" aria-labelledby={`${id}-method`}>
        <h3 id={`${id}-method`}>{selected}: {text(method.summary)}</h3>
        <ol className="flow-grid">
          {steps.map((step, index) => (
            <li className="flow-step" key={step.title}>
              <p className="mono">0{index + 1}</p>
              <h4>{text(step.title)}</h4>
              <p>{text(step.text)}</p>
            </li>
          ))}
        </ol>
      </div>
      <p className="note"><strong>{tr('Shared ceiling: 50,000 repository-information tokens.')}</strong> {tr('The cl100k_base ledger counts newly delivered repository blocks, including repeated acquisitions. Replayed history is not charged again. This is not a total-input, compute, latency, or cost budget; S1 native argument-validation feedback also bypasses this ledger.')}</p>
      <div className="note">
        <h3>{tr('S0 and S1 are distinct bundled configurations')}</h3>
        <p><strong>{tr('S0 — original confirmatory study.')}</strong> {tr('Arm-specific source filters, a 40,000-chunk RAG cap, text-JSON Agent tools, and more permissive final parsing. The RAG cap excluded two target files; eligibility and actual source delivery are different measurements.')}</p>
        <p><strong>{tr('S1 — supplemental study on the same known 80 entries.')}</strong> {tr('Shared source authorization, full nonblank indexes, native Agent tools, stricter interval validation, and changed rendering, retrieval ties, scheduling, and timeout semantics. These changes were bundled after S0 outcomes were known—not an independent replication or a causal ablation.')}</p>
        <p className="muted">{tr('Sources: frozen S0 arms.py and protocol; frozen S1 methods.py and protocol.py; manuscript Methodology, Experimental Setup, and configuration-change table.')}</p>
      </div>
    </section>
  );
}

export default MethodExplorer;
