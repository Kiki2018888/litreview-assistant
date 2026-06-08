import { useState, useCallback } from 'react'
import { apiGet, apiPost, apiPut, apiDelete } from '@/api/client'
import type { Paper, PaperListResponse, Batch } from '@/types'

export function useLiterature() {
  const [papers, setPapers] = useState<Paper[]>([])
  const [loading, setLoading] = useState(false)

  const fetchPapers = useCallback(async (params?: Record<string, string>) => {
    setLoading(true)
    const query = params ? '?' + new URLSearchParams(params).toString() : ''
    const data = await apiGet<PaperListResponse>(`/literature/${query}`)
    setPapers(data.items)
    setLoading(false)
  }, [])

  return { papers, loading, fetchPapers }
}
