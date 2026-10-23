import { toast } from 'vue-sonner'

import { ApiError } from '@/api/client'

/** Error toast for a failed request: the server's Korean `detail` goes in the description. */
export const toastError = (title: string) => (e: unknown) => toast.error(title, { description: e instanceof ApiError ? e.message : undefined })

/** Message for a failed request when it is shown as the toast description itself. */
export const errorMessage = (e: unknown) => (e instanceof ApiError ? e.message : '요청이 실패했습니다.')
