"""Summarize exported baselines without inventing human scores or billed costs."""
import argparse
import json
from collections import Counter
from pathlib import Path


def generate(root):
    labels = ('dev-a', 'dev-b', 'frozen-baseline')
    runs = {label: json.loads((root / f'{label}.json').read_text()) for label in labels}
    budget = json.loads((root / 'budget-final.json').read_text())
    lines = ['# 任务 1 真实评测基线', '',
             f"三批共 120 题已执行。含历史诊断累计 {budget['requests']} 次请求，保守预算预留 {float(budget['reserved_cny']):.2f} / {budget['limit_cny']} 元；预留不是实际账单。", '',
             '固定条件：qwen3.7-plus，温度 0，历史窗口 3，输出上限 2048，关闭思考及自动重试，top_n=5、相似度阈值 0.2。[完整配置](execution-config.json)。', '',
             '正确性与引用支持尚待人工复核；以下成功率仅指执行成功，费用为原价估算而非账单。', '',
             '| 批次 | 题数 | 执行成功 | 召回均值 | 输入 tokens | 输出 tokens | P95 秒 |',
             '|---|---:|---:|---:|---:|---:|---:|']
    notes = []
    for label, run in runs.items():
        summary = run['summary']
        rows = run['cases']
        known = all(row.get('input_tokens') is not None and row.get('output_tokens') is not None for row in rows)
        inputs = sum(row.get('input_tokens') or 0 for row in rows)
        outputs = sum(row.get('output_tokens') or 0 for row in rows)
        recall = summary.get('evidence_recall')
        lines.append(f"| {label} | {len(rows)}/{run['total']} | {summary['successful_execution_count']} | "
                     f"{format(recall, '.2%') if recall is not None else '未知'} | {inputs if known else '部分未知'} | "
                     f"{outputs if known else '部分未知'} | {summary.get('p95_seconds', 0):.2f} |")
        failures = dict(Counter(row.get('error') for row in rows if row['status'] != 'success'))
        notes.extend(['', f"{label}: `{run['run_id']}`；失败类型 `{failures}`。",
                      f"已知用量的北京原价估算（不扣缓存优惠）：{(inputs*2+outputs*8)/1000000:.6f} 元。"
                      + ('部分用量未知，不能视为完整估算。' if not known else '')])
    lines.extend(notes)
    lines.extend(['', '召回均值的有效样本数依次为：' + '、'.join(str(runs[label]['summary']['evidence_recall_sample_count']) for label in labels) + ' 题。',
                  '费用估算来源：[阿里云官方模型价目](https://help.aliyun.com/zh/model-studio/qwen3-7-plus)，北京档每百万输入 2 元、输出 8 元；Token Plan 实际套餐扣量或账单并不等于此估算。'])
    lines.extend(['', '## 冻结集证据缺失', ''])
    missing = [row for row in runs['frozen-baseline']['cases']
               if row.get('score', {}).get('evidence_recall') is not None
               and row['score']['evidence_recall'] < 1]
    lines.extend(['以下仅表示未检索到全部预设证据，不直接等同于答案错误。', ''])
    for row in missing:
        lines.append(f"- {row['case_id']}：召回 {row['score']['evidence_recall']:.3f}，"
                     f"缺失 {row['score'].get('missing_evidence_ids', [])}")
    if not missing:
        lines.append('无已知证据缺失；未知计量及答案支持仍需独立检查。')
    left = {row['case_id']: row for row in runs['dev-a']['cases']}
    right = {row['case_id']: row for row in runs['dev-b']['cases']}
    shared = sorted(left.keys() & right.keys())
    changes = {field: [key for key in shared if left[key].get(field) != right[key].get(field)]
               for field in ('answer', 'retrieved_evidence_ids', 'status')}
    lines.extend(['', '## 两次开发集对照', '',
                  '按 case_id 比较；答案文字变化不等于语义质量变化，少量重复运行不能证明统计显著性。', '',
                  f"答案文字不同：{len(changes['answer'])}/{len(shared)}；证据集合不同："
                  f"{len(changes['retrieved_evidence_ids'])}/{len(shared)}；执行状态不同：{len(changes['status'])}/{len(shared)}。", '',
                  '变动题：`' + json.dumps(changes, ensure_ascii=False) + '`', '',
                  '## 解释范围', '',
                  '- P95 包含每题独立进程冷启动与多轮总耗时，并非单次模型服务延迟。',
                  '- 工具超时为预先注入的只读工作流故障，不能计为任务完成。',
                  '- 多轮题的召回按全题各轮检索证据并集计算，不能证明最终一轮仍保有或正确使用这些证据。',
                  '- 人工正确率、引用准确率和每正确任务实际费用暂不报告。',
                  '- 题集为小规模合成夹具；冻结集不用于本轮调参。'])
    lines.extend(['', '## 优先人工复核与下一步假设', '',
                  '- 开发集 dev-11 的指代、dev-12 的人数条件及 dev-13 的预约状态：核对是否在十轮干扰后仍保留必要条件，不以提到关键词作为通过。',
                  '- dev-12 的能否使用讨论室还涉及开放时间和预约条件；对合理的条件性回答进行人工判断，避免把评分规则的不充分当成模型错误。',
                  '- 后续会话记忆实验：同题固定检索、模型及输出上限，只改变历史保留策略，检查条件错误是否下降及输入 token 是否增加。',
                  '- 后续去重实验：同题固定候选集合，对比保留重复证据与合并重复证据的实际输入 token、正确性及引用支持；当前基线不能证明去重有效。',
                  '- 工具恢复实验需区分预设超时与供应商/基础设施错误；恢复策略应同时衡量成功率、重试消耗和额外延迟。'])
    (root / 'baseline-report.md').write_text('\n'.join(lines) + '\n')
    review = ['# 人工复核清单', '', '逐题核对语义与完整证据。空白代表尚未复核，不能作为正确或错误。', '']
    corpus = json.loads((Path(__file__).resolve().parents[1] / 'evaluation/corpus.json').read_text())
    evidence = {item['evidence_id']: item['text'] for item in corpus['documents']}
    for label, run in runs.items():
        review.extend([f'## {label}', '', f"运行 `{run['run_id']}`", ''])
        questions = {case['case_id']: case for case in run['questions']}
        for row in run['cases']:
            case = questions[row['case_id']]
            review.extend([f"### {row['case_id']} · {case['scenario']}", '',
                           '**对话问题**', '', *[f'{i+1}. {q}' for i, q in enumerate(case['turns'])], '',
                           '**最终答案**', '', row.get('answer') or '（无答案）', '',
                           '**预期事实及规则**', '', json.dumps({key: case.get(key) for key in
                            ('expected_facts', 'acceptable_answers', 'rubric')}, ensure_ascii=False), '',
                           '**必需证据**', '', *[evidence[e] for e in case.get('required_evidence_ids', [])], '',
                           '正确性：____；引用总数：____；支持主张引用数：____；原因：____；复核人/时间：____', ''])
    (root / 'human-review.md').write_text('\n'.join(review).rstrip() + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output_dir', type=Path)
    generate(parser.parse_args().output_dir)
