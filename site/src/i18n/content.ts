import { content, type ContentPage } from '../content/pages';
import type { Locale } from './index';

const chinese: Record<keyof typeof content, ContentPage> = {
  analysis: {
    eyebrow: '解读实验证据', title: '上下文获取不等同于可靠定位',
    intro: '本研究区分源码是否可用、源码是否到达模型、模型返回哪些位置，以及最终输出能否使用。单一召回率无法同时概括这四个维度。',
    sections: [
      { title: 'FR@5 与 LR@5 衡量什么', body: [
        '文件级召回率 FR@5 衡量前五项预测对一到两个去重后的入口点（EP）和关键操作（CO）标注文件的覆盖。它是召回率而非精确率；报告的均值按条目加权，而不是合并所有目标文件后计算。',
        '即使 EP 与 CO 位于同一文件，行级召回率 LR@5 仍保留两个标注机会。同文件预测区间在五行容差下与标注重叠即可得分。该指标不要求精确行号、狭窄区间、正确解释或漏洞利用验证；宽区间也可能得分。',
        '空或无效的最终输出在两项指标上均计零分，且保留在所有分母中。S0 的解析器已将预测限制为五项；审计确认其 LR 函数缺少第二次切片并未改变 720 条记录中的任何分数。',
      ] },
      { title: '上下文获取、区间范围与输出完成', body: [
        '共享源码可用范围不保证源码实际交付，交付也不能证明模型使用了证据。论文利用历史诊断分析这些差异；L1 网站不重生成或绘制依赖原始轨迹的这些测量。',
        '基于容差的区间命中，本身不能证明模型获取了对应源码。宽预测区间可能得分；已存储指标无法判断命中来自标题、其他源码还是模型知识。',
        '结果探索器同时报告失败输出与召回率。排除失败输出会改变比较总体。论文讨论的关联不构成因果证明，也不能估计修复后系统的表现。',
      ] },
      { title: '配对推断，而非 240 个独立样本', body: [
        '每项研究包含 80 个条目 × 三种方法 × 三次重复。配对比较前先在条目内平均重复结果，因此条目级分析的 n = 80。S0 与 S1 始终分别报告，不合并推断。',
        '冻结的主要比较为 Agent–Pack 的 FR@5。四项次要比较在文件级与行区间召回率上比较 Agent–RAG 和 RAG–Pack，并按 q = 0.10 进行 Benjamini–Hochberg 校正。冻结过程使用 100,000 次 Monte Carlo 符号翻转和 10,000 次 bootstrap 抽样；S0 与 S1 保留各自不同的数值实现。',
        '13 个仓库分组并不均衡，80 个条目中有 45 个来自同一仓库。条目独立性是一项假设。论文的仓库敏感性诊断既不证明独立性，也不提供通用聚类稳健估计量。S1 未能确立 Agent 相对 RAG 的文件级召回优势。',
      ] },
      { title: '比较的限制', body: [
        '两项研究均使用记录的 DeepSeek V4 Pro / high 配置及同一批已知样本。S1 在观察 S0 后同时引入多项实现变更，因此跨研究差异不能归因于其中任何单项变更。',
        '数据集提供的标题可能包含目标文件名。仅基于描述的 NO_PATH_HINT 标记不能证明输入不含线索。Pack 是较弱的词法参考方法；共同的 50,000 个仓库信息 token 上限并不等同于累计模型输入、计算、费用或延迟相同。',
        '来源：docs/METHODS.md、paper/sections/03_methodology.tex 至 07_threats_to_validity.tex，以及 paper/main.tex。',
      ] },
    ],
  },
  reproducibility: {
    eyebrow: '科研制品边界', title: '离线复现已存储分数的分析',
    intro: '已实现的 L1 流程验证并重新聚合已存储指标，无模型调用，也不需要 API Key；它不是对原始预测的独立重评分，也不是新的模型实验。',
    sections: [
      { title: 'L1 验证哪些内容', body: [
        '验证覆盖哈希、每项研究 720 个唯一调度单元、80 个条目、允许的分数结构及失败输出计零。复现会比较全部五组冻结比较、正式数值参考，以及支持的论文表格与差值。',
        'S0 指标是在工程打包阶段从独立审计 CSV 派生，并逐条与原始记录和冻结评分器核验。S1 还与正式逐条分数一致。分发的仅指标数据无法独立重审标注或预测文本。',
      ] },
      { title: '环境与生成输出', body: [
        '已验证的解释器为 Python 3.12。NumPy 固定为 2.5.3，以保留历史 S1 数值和随机数行为。依赖安装可能需要联网；分析本身离线运行，无需模型 SDK。',
        '全部研究复现会生成包含六行的 results/main_results.json、CSV 和 Markdown 合并表。单研究运行只更新自身表格和统计，不重写合并表。网站数据契约要求 verify-results 拒绝缺失、重复、篡改或非有限值数据。',
        '每项研究的统计文件记录输入哈希、分析种子及 Python/NumPy 版本。这些是工程阶段派生的 L1 来源记录，不能替代历史原始来源记录。',
      ] },
      { title: '尚未完成的能力', body: [
        '依赖原始轨迹的 L2 图表重生成尚未完整实现。仓库内论文图为存量资源，并非本次新生成。源码交付、区间宽度和提供方输入图依赖被排除的原始记录或第三方资源。',
        '公开包装器未提供可支持的在线采集功能。历史运行器依赖私有资源和历史启动契约，且可能产生费用：仅供审查，不应从该科研制品直接运行。不能假设任何未来提供方能够重现历史回答。',
        '具备 TeX 依赖时，论文构建可编译随附快照而不覆盖存量 PDF；这不会重生成图表，也不重新验证论文全部论断。',
      ] },
      { title: '数据与发布保障', body: [
        '不包含原始回答、提示、思维内容、工具结果、漏洞公告文本、仓库检出、embedding、索引和模型事件日志。网站只使用已验证的 L1 结果输出，不读取私有本地资源或缓存。',
        '当前已按所列许可公开：代码采用 Apache-2.0，仅指标数据、论文与图采用 CC BY 4.0。个人作者、机构、发表场所与 DOI 仍待确认。不要整体上传工作目录；被忽略的本地快照是私有材料，且不是已验证的独立原始数据备份。',
        '来源：docs/REPRODUCIBILITY.md、docs/DATA_CARD.md、docs/INSTALL.md 与 README.md。',
      ] },
    ],
  },
  paper: {
    eyebrow: '论文快照', title: '面向漏洞公告引导的漏洞定位：证据获取与输出可靠性',
    intro: '在仓库信息上限约束下，使用同一模型比较只读自适应探索、单轮混合检索与词典序上下文打包。',
    sections: [
      { title: '摘要概述 — 意译概述，非论文原始摘要', body: [
        '两项分别报告的研究使用 DeepSeek V4 Pro，评估同一批已知 VulnGym 条目。输入包括数据集提供的标题，其中可能含有目标文件名。共同的 50,000 token 上限约束仓库信息获取，而非所有模型输入。',
        '补充研究中，自适应探索交付的标注源码明显更多，但文件级召回均值低于检索。被保留的失败输出实质性影响这一比较。检索在未获得对应源码时产生的容差区间命中，常依赖较宽预测范围；语法有效的回答仍可能包含不存在的路径或越界坐标。',
        '探索方法返回较窄区间，并取得更高的容差行级召回率，但推断支持对仓库依赖敏感，累计提供方输入也更多。论文主张联合报告源码交付、标注覆盖、区间范围和输出有效性，而非仅凭召回率给出获取策略的普适排名。',
      ] },
      { title: '研究设计与范围', body: [
        'S0 为原始确认性比较。S1 在其正式采集前冻结，但此时已知 S0 结果与实现问题。S1 同时改变授权、索引、交互、解析、展示、调度与计时；它是已知条目上的补充比较，不是独立确认或单因素消融。',
        '任务根据给定漏洞公告与固定版本仓库预测可能的漏洞位置，不评估未知漏洞发现、漏洞利用、补丁生成或商用漏洞扫描能力。静态引导检索尚未实现。',
      ] },
      { title: '研究贡献', body: ['论文通过实证刻画聚合定位召回率未能解释的维度，并非声称 Agent 普遍优于其他方法。'], items: [
        '在记录的标题辅助定位任务上，分别报告三种已实现上下文获取配置的比较。',
        '联合解释源码可用性、标注角色、预测区间范围和输出有效性。',
        '保留全部失败输出进行完整分母分析，区分输出结构有效与仓库位置有效。',
      ] },
      { title: '阅读随附快照', body: [
        'paper/ 包含论文源码、表格和存量图。L1 重生成主要统计结果，而非每张依赖原始轨迹的图或诊断。论文讨论的部分历史记录并未在本制品中全部分发。',
        '个人作者、机构、发表场所和 DOI 仍待确认。CITATION.cff 记录仓库引用信息，不编造署名。本页提供编辑性概述，不复制 PDF，也不指定尚未确认的作者。',
        '来源：paper/main.tex、paper/sections/03_methodology.tex、paper/sections/04_experimental_setup.tex、paper/sections/06_analysis_discussion.tex 及 docs/REPRODUCIBILITY.md。',
      ] },
    ],
  },
  resources: {
    eyebrow: '资源指南', title: '浏览科研制品',
    intro: '以下是本地候选仓库中的路径，不代表承诺公开下载、已获许可的数据发布或可支持的在线服务。',
    sections: [
      { title: '先了解已说明的边界', body: ['项目概述、方法和数据卡说明测量内容、分发范围，以及科研制品能够复现的结论。'], items: [
        'README.md — 研究概述、结果摘要、限制与发布状态。',
        'docs/METHODS.md — 指标定义、统计单位、冻结数值实现与 S0 Top-5 实现审计。',
        'docs/DATA_CARD.md — 仅指标结构、提取来源与排除内容。',
        'docs/REPRODUCIBILITY.md 与 docs/INSTALL.md — 离线流程、环境及尚未完成的复现层级。',
      ] },
      { title: '查看方法与结果', body: ['冻结科研源码保留用于审查，并非可移植的付费模型入口。离线包装器验证已存储指标，不修改历史方法。'], items: [
        'experiments/s0_frozen/ 与 experiments/s1_frozen/ — 冻结代码、配置、选定协议文档和源码哈希。',
        'data/processed/ — 最小条目元数据、调度、仅指标记录与正式参考。',
        'results/main_results.json — 经验证的六行网站接口，分别记录 S0/S1 元数据。',
        'results/s0_statistics.json 与 results/s1_statistics.json — 重生成的冻结比较、不确定性及输入哈希。',
        'docs/provenance/ — 来源哈希、提取检查、文件映射与完整性记录。',
      ] },
      { title: '论文与署名', body: [
        'paper/main.tex 与 paper/sections/ 包含论文快照；paper/tables/ 与 paper/figures/ 包含支持资源。paper/ARTIFACT_GUIDE.md 解释候选制品较窄的离线范围。存量图不能描述为新生成。',
        'CITATION.cff 记录仓库引用信息，个人作者、机构、发表场所与 DOI 仍待确认。LICENSE 将 Apache-2.0 授予代码；LICENSE-DATA 将 CC BY 4.0 授予仅指标数据、论文与图。LICENSING.md 说明适用范围，THIRD_PARTY_NOTICES.md 记录上游署名与排除内容。',
      ] },
      { title: '发布与维护', body: [
        '请查阅 docs/RELEASE_CHECKLIST.md 与 SECURITY.md。发布记录载明所有者授权、所选许可、待确认署名及已披露的残余风险。应独立保存私有科研原件，并且只发布明确审查通过的候选文件。',
        '来源：README.md、docs/DATA_CARD.md、docs/REPRODUCIBILITY.md、docs/RELEASE_CHECKLIST.md 及 paper/ARTIFACT_GUIDE.md。',
      ] },
    ],
  },
};

export function localizedContent(locale: Locale, page: keyof typeof content): ContentPage {
  return locale === 'zh' ? chinese[page] : content[page];
}
export const articlePages = Object.keys(content) as (keyof typeof content)[];
