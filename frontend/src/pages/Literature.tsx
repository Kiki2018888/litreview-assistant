import { useState, useEffect, useCallback } from "react"
import FileUploader from "../components/FileUploader"
import LiteratureList from "../components/LiteratureList"
import LiteratureDetail from "../components/LiteratureDetail"
import { apiGet } from "../api/client"
import type { Batch, BatchListResponse } from "../types"

export default function Literature() {
  const [refreshKey, setRefreshKey] = useState(0)
  const [batches, setBatches] = useState<Batch[]>([])

  // 多选状态（父组件控制，传给 LiteratureList 受控使用）
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  // 详情面板状态
  const [detailPaperId, setDetailPaperId] = useState<string | null>(null)

  // 加载批次列表（用于上传时选择）
  useEffect(() => {
    apiGet<BatchListResponse>("/batches/?page=1&page_size=100")
      .then((res) => setBatches(res.items))
      .catch(() => setBatches([]))
  }, [refreshKey])

  // 上传完成后刷新列表和批次
  const handleUploadComplete = useCallback(() => {
    setRefreshKey((k) => k + 1)
    setSelectedIds([])
  }, [])

  // 关闭详情面板
  const handleCloseDetail = useCallback(() => {
    setDetailPaperId(null)
  }, [])

  // 刷新（提取完成/删除后触发）
  const handleRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  // 是否显示详情面板
  const showDetail = detailPaperId !== null

  return (
    <div className="flex h-full">
      {/* ── 左侧：列表区 ── */}
      <div
        className="flex flex-col min-w-0 overflow-y-auto p-6"
        style={{ width: showDetail ? "40%" : "100%", transition: "width 0.2s ease" }}
      >
        {/* 上传区域 */}
        <FileUploader
          onUploadComplete={handleUploadComplete}
          batches={batches}
        />

        {/* 分隔 */}
        <hr className="border-border my-6" />

        {/* 文献列表 */}
        <LiteratureList
          refreshKey={refreshKey}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          onSelectPaper={setDetailPaperId}
        />
      </div>

      {/* ── 右侧：详情面板（滑出） ── */}
      {showDetail && (
        <div
          className="border-l border-border bg-background overflow-hidden"
          style={{ width: "60%", transition: "width 0.2s ease" }}
        >
          <LiteratureDetail
            paperId={detailPaperId}
            onClose={handleCloseDetail}
            onRefresh={handleRefresh}
          />
        </div>
      )}
    </div>
  )
}
