import { useState, useEffect, useCallback } from "react"
import FileUploader from "../components/FileUploader"
import LiteratureList from "../components/LiteratureList"
import { apiGet } from "../api/client"
import type { Batch, BatchListResponse } from "../types"

export default function Literature() {
  const [refreshKey, setRefreshKey] = useState(0)
  const [batches, setBatches] = useState<Batch[]>([])
  // 多选状态（父组件控制，传给 LiteratureList 受控使用）
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  // 加载批次列表（用于上传时选择）
  useEffect(() => {
    apiGet<BatchListResponse>("/batches/?page=1&page_size=100")
      .then((res) => setBatches(res.items))
      .catch(() => setBatches([]))
  }, [refreshKey])

  // 上传完成后刷新列表和批次
  const handleUploadComplete = useCallback(() => {
    setRefreshKey((k) => k + 1)
    setSelectedIds([]) // 上传后清空选择
  }, [])

  return (
    <div className="space-y-6 p-6">
      {/* 上传区域 */}
      <FileUploader
        onUploadComplete={handleUploadComplete}
        batches={batches}
      />

      {/* 分隔 */}
      <hr className="border-border" />

      {/* 文献列表 */}
      <LiteratureList
        refreshKey={refreshKey}
        selectedIds={selectedIds}
        onSelectionChange={setSelectedIds}
      />
    </div>
  )
}
