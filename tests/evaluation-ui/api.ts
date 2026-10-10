const state = new URLSearchParams(location.search).get('state') || 'pending'
const cases: any[] = [
  { case_id: 'dev-01', scenario: 'direct', status: 'success', answer: '青禾图书室周一闭馆。 [D-hours]', retrieved_evidence_ids: ['D-hours'], citations: ['D-hours'], trace: [{ node_id: 'search', status: 200 }], review: {} },
  { case_id: 'dev-16', scenario: 'tool_timeout', status: 'failed', answer: '', error: 'tool_timeout', trace: [{ node_id: 'readonly-lookup', status: 500 }], review: {} },
]
const summary = { accuracy: null, review_coverage: 0, evidence_recall: 1, citation_accuracy: null,
 tool_complete: 0, average_input_tokens: null, average_output_tokens: null, input_token_coverage: 0,
 output_token_coverage: 0, cost_per_success: null, cost_coverage: 0, p95_seconds: 2.1 }
const runs = ['11111111-demo', '22222222-demo'].map(run_id => ({ run_id, status: state === 'running' ? 'running' : 'completed', dataset_version: 'dev-v1', created_at: '2026-10-09T08:00:00Z', progress: 2, total: 20, summary }))
export default {
 list: async () => ({ data: state === 'empty' ? [] : runs }),
 detail: async (_: string, run: string) => ({ data: { ...runs.find(r => r.run_id === run), cases, snapshot: { code_sha: 'UI fixture — not a real baseline', model_version_status: 'unknown' }, questions: [{ case_id: 'dev-01', turns: ['周一开放吗？'], expected_facts: ['周一闭馆'], required_evidence_ids: ['D-hours'] }] } }),
 create: async () => ({ data: runs[0] }),
 compare: async () => ({ data: { comparable: state !== 'incomparable', reasons: state === 'incomparable' ? ['image_id'] : [], left_summary: summary, right_summary: summary, cases: cases.map(c => ({ case_id: c.case_id, left: c, right: c })) } }),
 review: async (_: string, __: string, caseId: string, data: any) => { const c = cases.find(c => c.case_id === caseId); c.review = { ...data, reviewer: 'UI-test', reviewed_at: '2026-10-09T08:00:00Z' }; return { data: c.review } },
}
