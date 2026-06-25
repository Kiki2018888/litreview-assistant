import { Hammer } from "lucide-react"

/**
 * 统一占位文案 —— 信号发现模块（局限聚类/裁决/矛盾点/稀疏格/方法迁移）本版未发布，
 * 入口统一指向该文案。将来功能就绪后逐个替换回真实组件即可。
 */
export const COMING_SOON_MESSAGE = "该功能正在开发中，敬请期待"

interface ComingSoonProps {
  /** 占位标题，默认 "敬请期待" */
  title?: string
  /** 副标题说明，默认统一文案 */
  description?: string
}

/** 未完成功能的统一"敬请期待"占位页（零网络请求）。 */
export default function ComingSoon({
  title = "敬请期待",
  description = COMING_SOON_MESSAGE,
}: ComingSoonProps) {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-4 p-10 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
        <Hammer className="h-8 w-8 text-primary" />
      </div>
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      <p className="max-w-md text-sm text-muted-foreground">{description}</p>
    </div>
  )
}
