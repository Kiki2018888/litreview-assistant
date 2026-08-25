import { useState, useEffect, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import {
  FolderKanban,
  Plus,
  Pencil,
  Trash2,
  Loader2,
  FileText,
  Sparkles,
} from "lucide-react"
import { toast } from "sonner"
import { apiGet, apiPost, apiPut, apiDelete } from "../api/client"
import { Button } from "../components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "../components/ui/dialog"
import type {
  Project,
  ProjectCreateRequest,
  ProjectListResponse,
  ProjectUpdateRequest,
  ProjectDeleteResponse,
} from "../types"

// ============================================================================
// Projects 页面
// ============================================================================

export default function ProjectsPage() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Project | null>(null)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [saving, setSaving] = useState(false)

  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null)
  const [deleting, setDeleting] = useState(false)

  const fetchProjects = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiGet<ProjectListResponse>("/projects/?page=1&page_size=100")
      setProjects(res.items)
    } catch {
      toast.error("加载项目列表失败")
      setProjects([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  const openCreate = () => {
    setEditing(null)
    setName("")
    setDescription("")
    setFormOpen(true)
  }

  const openEdit = (project: Project) => {
    setEditing(project)
    setName(project.name)
    setDescription(project.description ?? "")
    setFormOpen(true)
  }

  const handleSave = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      toast.error("请输入项目名称")
      return
    }
    if (trimmed.length > 100) {
      toast.error("项目名称不能超过 100 字")
      return
    }

    setSaving(true)
    try {
      if (editing) {
        const body: ProjectUpdateRequest = {
          name: editing.is_default ? undefined : trimmed,
          description: description.trim() || null,
        }
        await apiPut(`/projects/${editing.id}`, body)
        toast.success("项目已更新")
      } else {
        const body: ProjectCreateRequest = {
          name: trimmed,
          description: description.trim() || null,
        }
        await apiPost("/projects/", body)
        toast.success("项目已创建")
      }
      setFormOpen(false)
      fetchProjects()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      const res = await apiDelete<ProjectDeleteResponse>(`/projects/${deleteTarget.id}`)
      toast.success(`已删除项目，${res.moved_count} 篇文献移入「未分类」`)
      setDeleteTarget(null)
      fetchProjects()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败")
    } finally {
      setDeleting(false)
    }
  }

  const openProjectLiterature = (project: Project) => {
    navigate(`/?project_id=${project.id}`)
  }

  const openProjectSignals = (project: Project) => {
    navigate(`/adjudication?project_id=${project.id}`)
  }

  const formatTime = (iso: string) => {
    try {
      return new Date(iso).toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    } catch {
      return iso
    }
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <FolderKanban className="h-5 w-5" />
            项目管理
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            按课题/研究方向分组管理文献，点击项目可查看该组文献
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4 mr-1.5" />
          新建项目
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin mr-2" />
          加载中…
        </div>
      ) : projects.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
          <FolderKanban className="h-12 w-12 opacity-30 mb-3" />
          <p className="text-sm">暂无项目，点击「新建项目」开始</p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <div
              key={project.id}
              className="rounded-lg border border-border bg-card p-4 hover:border-primary/40 transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <button
                  type="button"
                  onClick={() => openProjectLiterature(project)}
                  className="text-left flex-1 min-w-0"
                >
                  <h3 className="font-medium truncate" title={project.name}>
                    {project.name}
                    {project.is_default && (
                      <span className="ml-2 text-xs font-normal text-muted-foreground">
                        （默认）
                      </span>
                    )}
                  </h3>
                  {project.description && (
                    <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
                      {project.description}
                    </p>
                  )}
                </button>
                <div className="flex shrink-0 gap-1">
                  {!project.is_default && (
                    <>
                      <button
                        type="button"
                        onClick={() => openEdit(project)}
                        className="rounded p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted"
                        title="编辑"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteTarget(project)}
                        className="rounded p-1.5 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                        title="删除"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </>
                  )}
                </div>
              </div>

              <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <FileText className="h-3.5 w-3.5" />
                  {project.paper_count} 篇文献
                </span>
                <span>更新于 {formatTime(project.updated_at)}</span>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => openProjectLiterature(project)}
                >
                  查看文献
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => openProjectSignals(project)}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  发现机会
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 创建/编辑弹窗 */}
      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent onClose={() => setFormOpen(false)}>
          <DialogHeader>
            <DialogTitle>{editing ? "编辑项目" : "新建项目"}</DialogTitle>
            <DialogDescription>
              {editing?.is_default
                ? "默认项目「我的文献」仅可修改描述"
                : "项目名称 1-100 字，描述可选"}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <label className="text-sm font-medium">名称</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={!!editing?.is_default}
                maxLength={100}
                placeholder="例如：外泌体课题 A"
                className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring disabled:opacity-60"
              />
            </div>
            <div>
              <label className="text-sm font-medium">描述（可选）</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                placeholder="项目简介…"
                className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring resize-none"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFormOpen(false)} disabled={saving}>
              取消
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "保存中…" : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认 */}
      <Dialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <DialogContent onClose={() => setDeleteTarget(null)}>
          <DialogHeader>
            <DialogTitle>确定删除项目？</DialogTitle>
            <DialogDescription>
              将删除项目「{deleteTarget?.name}」。其中 {deleteTarget?.paper_count ?? 0}{" "}
              篇文献将移入「我的文献」，文献本身不会被删除。此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              取消
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? "删除中…" : "确定删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
