import { useState, useEffect, useCallback } from "react"
import { useSearchParams } from "react-router-dom"
import FileUploader from "../components/FileUploader"
import LiteratureList from "../components/LiteratureList"
import LiteratureDetail from "../components/LiteratureDetail"
import ChatPanel from "../components/ChatPanel"
import { apiGet } from "../api/client"
import type { Project, ProjectListResponse } from "../types"

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
  const [searchParams, setSearchParams] = useSearchParams()
  const projectFilter = searchParams.get("project_id") ?? ""

  const [refreshKey, setRefreshKey] = useState(0)
  const [projects, setProjects] = useState<Project[]>([])

  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [detailPaperId, setDetailPaperId] = useState<string | null>(null)
  const [chatMode, setChatMode] = useState<ChatMode>(null)

  useEffect(() => {
    apiGet<ProjectListResponse>("/projects/?page=1&page_size=100")
      .then((res) => setProjects(res.items))
      .catch(() => setProjects([]))
  }, [refreshKey])

  const handleProjectFilterChange = useCallback(
    (projectId: string) => {
      if (projectId) {
        setSearchParams({ project_id: projectId })
      } else {
        setSearchParams({})
      }
    },
    [setSearchParams]
  )

  const handleUploadComplete = useCallback(() => {
    setRefreshKey((k) => k + 1)
    setSelectedIds([])
  }, [])

  const handleCloseDetail = useCallback(() => {
    setDetailPaperId(null)
  }, [])

  const handleRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  const handleOpenChat = useCallback((paperId: string) => {
    setChatMode({ mode: "single", paperId })
  }, [])

  const handleChatMulti = useCallback((paperIds: string[]) => {
    if (paperIds.length === 0) return
    setChatMode({ mode: "multi", paperIds })
  }, [])

  const handleCloseChat = useCallback(() => {
    setChatMode(null)
  }, [])

  const showDetailOnly = detailPaperId !== null && chatMode === null

  const showDetailWithChat =
    detailPaperId !== null &&
    chatMode?.mode === "single" &&
    chatMode.paperId === detailPaperId

  const showChatOnly =
    chatMode !== null && !showDetailWithChat

  const leftWidth =
    showDetailOnly || showDetailWithChat || showChatOnly ? "40%" : "100%"

  return (
    <div className="flex h-full">
      <div
        className="flex flex-col min-w-0 overflow-y-auto p-6"
        style={{
          width: leftWidth,
          transition: "width 0.2s ease",
        }}
      >
        <FileUploader
          onUploadComplete={handleUploadComplete}
          projects={projects}
        />

        <hr className="border-border my-6" />

        <LiteratureList
          refreshKey={refreshKey}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          onSelectPaper={(id) => {
            setDetailPaperId(id)
            if (chatMode?.mode === "multi") setChatMode(null)
          }}
          onChatMulti={handleChatMulti}
          projects={projects}
          projectFilter={projectFilter}
          onProjectFilterChange={handleProjectFilterChange}
          onDeleted={handleRefresh}
        />
      </div>

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

      {showDetailWithChat && chatMode && (
        <div
          className="flex flex-col border-l border-border bg-background overflow-hidden"
          style={{ width: "60%", transition: "width 0.2s ease" }}
        >
          <div className="flex-1 overflow-hidden" style={{ flexBasis: "50%" }}>
            <LiteratureDetail
              paperId={detailPaperId}
              onClose={() => {
                setChatMode(null)
                handleCloseDetail()
              }}
              onRefresh={handleRefresh}
              onOpenChat={handleOpenChat}
            />
          </div>

          <div className="flex-1 overflow-hidden border-t border-border">
            <ChatPanel
              mode="single"
              paperId={chatMode.paperId}
              onClose={handleCloseChat}
            />
          </div>
        </div>
      )}

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
