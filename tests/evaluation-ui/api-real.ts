// Read-only preview of exported provider-backed runs; never calls the model or writes scores.
import first from '../../docs/implementation/evidence/task-1/real-runs/dev-a.json'
import second from '../../docs/implementation/evidence/task-1/real-runs/dev-b.json'
import comparison from '../../docs/implementation/evidence/task-1/real-runs/dev-comparison.json'
const runs = [first, second]
export default {
  list: async () => ({ data: runs }),
  detail: async (_: string, run: string) => ({ data: runs.find(item => item.run_id === run) }),
  compare: async (_: string, left: string, right: string) => {
    if (left !== first.run_id || right !== second.run_id) throw new Error('Preview supports dev-a versus dev-b only')
    return { data: comparison }
  },
  create: async () => { throw new Error('Read-only exported results') },
  review: async () => { throw new Error('Read-only exported results') },
}
