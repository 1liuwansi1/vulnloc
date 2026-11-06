import { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, ScatterChart, CustomChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, AriaComponent, MarkLineComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import type { EChartsCoreOption } from 'echarts/core';
import data from '../data/verified.json';
import { t, translate, format, number, languageTag, type Locale } from '../i18n';
import { useQueryState } from './useQueryState';

echarts.use([BarChart, ScatterChart, CustomChart, GridComponent, TooltipComponent, AriaComponent, MarkLineComponent, SVGRenderer]);
type Study = 's0' | 's1';
type Metric = 'file_recall5' | 'line_recall5' | 'failures';
type Contrast = { label: string; metric: string; difference: number; ci: number[]; p: number; q?: number };
const arms = ['agent', 'rag', 'pack'] as const;
const labels = { agent: 'Agent', rag: 'RAG', pack: 'Pack' };
const colors = ['#85dfe9', '#8faff4', '#b7a6e8'];

function Chart({ option, label }: { option: EChartsCoreOption; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: 'svg' });
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [option]);
  return <div className="chart" ref={ref} role="img" aria-label={label} />;
}

export default function ResultsExplorer({ locale = 'en' }: { locale?: Locale }) {
  const [study, setStudy] = useQueryState<Study>('study', ['s0','s1'], 's0');
  const [metric, setMetric] = useQueryState<Metric>('metric', ['file_recall5','line_recall5','failures'], 'file_recall5');
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  const tr = (key: Parameters<typeof t>[1]) => t(locale,key);
  const pct = (value: number) => number(locale,value * 100) + '%';
  const pp = (value: number) => (value > 0 ? '+' : '') + number(locale,value * 100);
  const probability = (value: number) => value === 0 ? tr('0.0000 (historically rounded)') : value < .0001 ? value.toExponential(3) : number(locale,value,4);
  const contrastName = (value: string) => translate(locale,value.replace('Rag','RAG'));
  const colon = locale === 'zh' ? '：' : ':';
  const value = data.studies[study];
  const contrasts: Contrast[] = [value.primary, ...value.secondary];
  const main = value.primary;
  const rag = value.secondary[0];
  const title = tr(metric === 'file_recall5' ? 'File recall · FR@5' : metric === 'line_recall5' ? 'Interval recall · LR@5' : 'Output failures');
  const reduced = typeof window === 'undefined' || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const option: EChartsCoreOption = {
    animation: !reduced, animationDuration: 350,
    aria: { enabled: false },
    textStyle: { fontFamily: 'Segoe UI, Arial, sans-serif', color: '#a0aebe' },
    grid: { top: 45, left: 50, right: 20, bottom: 45 },
    tooltip: { trigger: 'axis', backgroundColor: '#111d2b', borderColor: '#344859', textStyle: { color: '#e9eef5' }, valueFormatter: (v: unknown) => metric === 'failures' ? `${v} / ${value.units_per_arm} ${tr('units')}` : `${number(locale,Number(v))}%` },
    xAxis: { type: 'category', data: arms.map(a => labels[a]), axisLine: { lineStyle: { color: '#34404e' } }, axisTick: { show: false }, axisLabel: { color: '#c6d3e0', margin: 18 } },
    yAxis: { type: 'value', min: 0, max: metric === 'failures' ? value.units_per_arm : 100, name: tr(metric === 'failures' ? 'Failed units / 240' : 'Recall (%)'), nameTextStyle: { align: 'left', padding: [0, 0, 0, -35] }, splitLine: { lineStyle: { color: '#25303d', type: 'dashed' } }, axisLabel: { color: '#a0aebe' } },
    series: [{ type: 'bar', barMaxWidth: 95, data: arms.map((a, i) => ({ value: value.arms[a][metric] * (metric === 'failures' ? 1 : 100), itemStyle: { color: colors[i], borderRadius: [3, 3, 0, 0] } })), label: { show: true, position: 'top', color: '#d8e5f1', formatter: (p: { value: unknown }) => metric === 'failures' ? String(p.value) : Number(p.value).toFixed(2) + '%' } }],
  };
  const forest: EChartsCoreOption = {
    animation: false, aria: { enabled: false },
    textStyle: { color: '#a0aebe', fontFamily: 'Segoe UI, Arial, sans-serif' },
    grid: { top: 15, left: 128, right: 20, bottom: 45 },
    tooltip: { show: false },
    xAxis: { type: 'value', min: -100, max: 100, name: tr('Paired difference (percentage points)'), nameLocation: 'middle', nameGap: 28, nameTextStyle: { fontSize: 10 }, splitLine: { lineStyle: { color: '#25303d', type: 'dashed' } }, axisLabel: { fontSize: 10 } },
    yAxis: { type: 'category', inverse: true, data: contrasts.map(c => contrastName(c.label) + ' · ' + (c.metric === 'file_recall5' ? 'FR' : 'LR')), axisLabel: { color: '#bccbd9', fontSize: 10 }, axisTick: { show: false }, axisLine: { show: false } },
    series: [{ type: 'custom', data: contrasts.map((c,i) => [i, c.difference * 100, c.ci[0] * 100, c.ci[1] * 100]),
      renderItem: (_params: unknown, api: any) => {
        const middle = api.coord([api.value(1), api.value(0)]);
        const low = api.coord([api.value(2), api.value(0)]);
        const high = api.coord([api.value(3), api.value(0)]);
        return { type: 'group', children: [
          { type: 'line', shape: { x1: low[0], y1: low[1], x2: high[0], y2: high[1] }, style: { stroke: '#85dfe9', lineWidth: 2 } },
          ...[low, high].map(p => ({ type: 'line', shape: { x1: p[0], y1: p[1]-5, x2: p[0], y2: p[1]+5 }, style: { stroke: '#85dfe9', lineWidth: 2 } })),
          { type: 'circle', shape: { cx: middle[0], cy: middle[1], r: 4 }, style: { fill: '#85dfe9' } },
        ] };
      },
    }, { type: 'scatter', data: [], markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: '#9dacca', type: 'dashed' }, data: [{ xAxis: 0 }] } }],
  };
  return <div data-hydrated={hydrated ? 'true' : undefined}>
    <div className="tabs" aria-label={tr('Select study')}>{(['s0', 's1'] as const).map(s => <button key={s} aria-pressed={study === s} className={study === s ? 'active' : ''} onClick={() => setStudy(s)}>{s.toUpperCase()} · {tr(s === 's0' ? 'Confirmatory' : 'Supplemental')}</button>)}</div>
    <div aria-live="polite"><h2 style={{ fontSize: 30 }}>{tr(study === 's0' ? 'The original confirmatory study' : 'A supplemental study on known entries')}</h2><p>{format(locale,'{entries} entries · {units} inference units · {perArm} per arm · {repeats} repeats averaged within entry',{entries:value.entries,units:value.units,perArm:value.units_per_arm,repeats:value.repeats})}</p></div>
    {study === 's1' && <aside className="note">{tr('S1 is not independent confirmation. Bundled implementation changes and the same known entries prevent a causal interpretation of S0–S1 differences. Agent does not establish a file-recall advantage over RAG.')}</aside>}
    <div className="chart-shell"><div className="chart-title"><div><h2>{title}</h2><p>{tr('Fixed zero-origin axis · all failed outputs retained')}</p></div><div className="metric-buttons" aria-label={tr('Select metric')}>{(['file_recall5','line_recall5','failures'] as const).map(m => <button className={metric === m ? 'active' : ''} aria-pressed={metric === m} key={m} onClick={() => setMetric(m)}>{m === 'file_recall5' ? 'FR@5' : m === 'line_recall5' ? 'LR@5' : tr('Failures')}</button>)}</div></div><Chart option={option} label={`${study.toUpperCase()} ${title}. ${tr('Numerical values available in the following table.')}`} /><p className="source">{tr('Source')}{colon} results/main_results.json · {study}_statistics.json{locale === 'zh' ? '。' : '.'} {tr('Arm-level CIs are not supplied; paired-contrast CIs appear below.')}</p></div>
    <div className="table-wrap"><table data-testid="means"><caption>{format(locale,'{study} observed means · n = {entries} entries, not {perArm} independent samples',{study:study.toUpperCase(),entries:value.entries,perArm:value.units_per_arm})}</caption><thead><tr><th>{tr('Acquisition')}</th><th>FR@5</th><th>LR@5</th><th>{tr('Output failures')}</th><th>{tr('Units')}</th></tr></thead><tbody>{arms.map(a => <tr key={a}><td>{labels[a]}</td><td>{pct(value.arms[a].file_recall5)}</td><td>{pct(value.arms[a].line_recall5)}</td><td>{value.arms[a].failures} / {value.arms[a].units} ({pct(value.arms[a].failures / value.arms[a].units)})</td><td>{value.arms[a].units}</td></tr>)}</tbody></table></div>
    <p className="table-hint">{tr('Swipe tables horizontally to inspect every column ↔')}</p>
    <div className="contrast-grid">{[{key:'Primary / Agent − Pack · FR@5', item:main},{key:'Secondary / Agent − RAG · FR@5',item:rag}].map(({key,item}) => <article className="contrast-card" key={key}><span className="eyebrow">{translate(locale,key)}</span><div className="big-number">{pp(item.difference)} <span style={{fontSize:16}}>{tr('pp')}</span></div><p>{tr('95% entry-bootstrap CI')} [{pp(item.ci[0])}, {pp(item.ci[1])}] {tr('pp')}<br />{tr('Monte Carlo p')}: {probability(item.p)}</p></article>)}</div>
    <div className="chart-shell"><div className="chart-title"><div><h2>{tr('Paired contrasts & uncertainty')}</h2><p>{tr('Points = mean paired differences · lines = 95% entry-bootstrap CIs · dashed vertical = no difference')}</p></div></div><Chart option={forest} label={tr('Five paired differences with 95% confidence intervals, detailed in the following table.')} /></div>
    <div className="table-wrap"><table data-testid="contrasts"><caption>{tr('All frozen contrasts · differences and intervals in percentage points')}</caption><thead><tr><th>{tr('Contrast')}</th><th>{tr('Metric')}</th><th>{tr('Difference')}</th><th>{tr('95% CI')}</th><th>{tr('p (MC)')}</th><th>{tr('BH q')}</th></tr></thead><tbody>{contrasts.map((c,i) => <tr key={i}><td>{contrastName(c.label)}{i === 0 ? tr(' (primary)') : ''}</td><td>{c.metric === 'file_recall5' ? 'FR@5' : 'LR@5'}</td><td>{pp(c.difference)}</td><td>[{pp(c.ci[0])}, {pp(c.ci[1])}]</td><td>{probability(c.p)}</td><td>{c.q === undefined ? tr('Not in family') : probability(c.q)}</td></tr>)}</tbody></table></div>
    <aside className="note">{format(locale,'Inference uses {entries} entry-level pairs after averaging repeats. {bootstrap} bootstrap draws; {permutation} Monte Carlo sign flips; seed {seed}. The four secondary tests use BH at q = 0.10. S0 p = 0.0000 is historical rounding, not zero probability. Repository dependence limits inference: entry independence is assumed, not established.',{entries:value.entries, bootstrap:value.bootstrap_draws.toLocaleString(languageTag[locale]),permutation:value.permutation_draws.toLocaleString(languageTag[locale]),seed:value.seed})}</aside>
    <p className="source">{tr('The displayed percentages are derived from verified JSON, never hardcoded. Statistical CIs are for paired differences, not individual arms. Small display differences reflect presentation rounding; full-precision source values remain unchanged.')}</p>
  </div>;
}
