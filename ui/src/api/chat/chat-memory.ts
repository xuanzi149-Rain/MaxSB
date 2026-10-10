import { request as chatRequest } from '@/request/chat'
import { request as adminRequest } from '@/request'
import useStore from '@/stores'

export function memoryRequest(chatId: string, debug: boolean, applicationId: string, method: string, data?: any, factId?: string) {
  const workspace = useStore().user.getWorkspaceId()
  const prefix = debug ? `/workspace/${workspace}/application/${applicationId}` : ''
  const url = `${prefix}/chat_memory/${chatId}${factId ? `/facts/${factId}` : ''}`
  return (debug ? adminRequest : chatRequest)({ url, method, data }).then((r) => r.data.data)
}
