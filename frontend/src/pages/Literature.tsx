import { useState, useEffect, useCallback } from "react"
import FileUploader from "../components/FileUploader"
import LiteratureList from "../components/LiteratureList"
import LiteratureDetail from "../components/LiteratureDetail"
import ChatPanel from "../components/ChatPanel"
import { apiGet } from "../api/client"
import type { Batch, BatchListResponse } from "../types"

// ============================================================================
// Chat 模式
// ============================================================================

type ChatMode =
  | { mode: "single"; paperId: string }
  | { mode: "multi"; paperIds: string[] }
  | null

// ============================================================================
// Literature 页面
// ============================================================================

export default function Literature() {
  const [refreshKey, setRefreshKey] = useState(0)
  const [batches, setBatches] = useState<Batch[]>([])

  // 多选状态（父组件控制，传给 LiteratureList 受控使用）
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  // 详情面板状态
  const [detailPaperId, setDetailPaperId] = useState<string | null>(null)

  // ChatPanel 状态
  const [chatMode, setChatMode] = useState<ChatMode>(null)

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

  // 打开精读面板（从 LiteratureDetail 触发）
  const handleOpenChat = useCallback((paperId: string) => {
    setChatMode({ mode: "single", paperId })
  }, [])

  // 打开跨文献问答（从 LiteratureList 多选条触发）
  const handleChatMulti = useCallback((paperIds: string[]) => {
    if (paperIds.length === 0) return
    setChatMode({ mode: "multi", paperIds })
  }, [])

  // 关闭 ChatPanel
  const handleCloseChat = useCallback(() => {
    setChatMode(null)
  }, [])

  // ── 显示控制（问题3修复：精读时不隐藏 Detail） ──

  // 是否仅显示 Detail（无 ChatPanel）
  const showDetailOnly = detailPaperId !== null && chatMode === null

  // 是否同时显示 Detail + ChatPanel（单篇精读且对应同一篇文献）
  const showDetailWithChat =
    detailPaperId !== null &&
    chatMode?.mode === "single" &&
    chatMode.paperId === detailPaperId

  // 是否仅显示 ChatPanel（跨文献问答，或精读但未打开 Detail）
  const showChatOnly =
    chatMode !== null && !showDetailWithChat

  // 左侧列表宽度
  const leftWidth =
    showDetailOnly || showDetailWithChat || showChatOnly ? "40%" : "100%"

  return (
    <div className="flex h-full">
      {/* ── 左侧：列表区 ── */}
      <div
        className="flex flex-col min-w-0 overflow-y-auto p-6"
        style={{
          width: leftWidth,
          transition: "width 0.2s ease",
        }}
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
          onSelectPaper={(id) => {
            setDetailPaperId(id)
            // 如果正在跨文献问答，关闭 chat
            if (chatMode?.mode === "multi") setChatMode(null)
          }}
          onChatMulti={handleChatMulti}
        />
      </div>

      {/* ── 右侧：仅 Detail ── */}
      {showDetailOnly && (
        <div
          className="border-l border-border bg-background overflow-hidden"
          style={{ width: "60%", transition: "width 0.2s ease" }}
        >
          <LiteratureDetail
            paperId={detailPaperId}
            onClose={handleCloseDetail}
            onRefresh={handleRefresh}
            onOpenChat={handleOpenChat}
          />
        </div>
      )}

      {/* ── 右侧：Detail + ChatPanel 上下分栏（精读模式） ── */}
      {showDetailWithChat && chatMode && (
        <div
          className="flex flex-col border-l border-border bg-background overflow-hidden"
          style={{ width: "60%", transition: "width 0.2s ease" }}
        >
          {/* 上半部分：Detail（含 PdfViewer） */}
          <div className="flex-1 overflow-hidden" style={{ flexBasis: "50%" }}>
            <LiteratureDetail
              paperId={detailPaperId}
              onClose={() => {
                // 关闭 Detail 时也关闭精读 chat
                setChatMode(null)
                handleCloseDetail()
              }}
              onRefresh={handleRefresh}
              onOpenChat={handleOpenChat}
            />
          </div>

          {/* 下半部分：ChatPanel */}
          <div className="flex-1 overflow-hidden border-t border-border">
            <ChatPanel
              mode="single"
              paperId={chatMode.paperId}
              onClose={handleCloseChat}
            />
          </div>
        </div>
      )}

      {/* ── 右侧：仅 ChatPanel（跨文献问答 / 孤立精读） ── */}
      {showChatOnly && chatMode && (
        <div
          className="border-l border-border bg-background overflow-hidden"
          style={{ width: "60%", transition: "width 0.2s ease" }}
        >
          {chatMode.mode === "single" ? (
            <ChatPanel
              mode="single"
              paperId={chatMode.paperId}
              onClose={handleCloseChat}
            />
          ) : (
            <ChatPanel
              mode="multi"
              paperIds={chatMode.paperIds}
              onClose={handleCloseChat}
            />
          )}
        </div>
      )}
    </div>
  )
}
