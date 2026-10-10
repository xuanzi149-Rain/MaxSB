import { get, post, put } from '@/request/index'
import useStore from '@/stores'
const base = (id: string) => `/workspace/${useStore().user.getWorkspaceId()}/application/${id}/evaluation`
export default {
  list: (id: string) => get(`${base(id)}/runs`),
  create: (id: string, dataset_version: string) => post(`${base(id)}/runs`, { dataset_version }),
  detail: (id: string, run: string) => get(`${base(id)}/runs/${run}`),
  compare: (id: string, left: string, right: string) => get(`${base(id)}/compare`, { left, right }),
  review: (id: string, run: string, caseId: string, data: any) =>
    put(`${base(id)}/runs/${run}/cases/${caseId}/review`, data),
}
