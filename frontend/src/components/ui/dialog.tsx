import { useEffect, useState } from "react"
import { X } from "lucide-react"
import { cn } from "../../lib/utils"

// ============================================================================
// Dialog — controlled modal dialog (no @radix-ui dependency)
// ============================================================================

interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: React.ReactNode
}

function Dialog({ open, onOpenChange, children }: DialogProps) {
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    if (open) {
      setMounted(true)
      document.body.style.overflow = "hidden"
    } else {
      // Delay unmount for exit animation
      const timer = setTimeout(() => {
        setMounted(false)
        document.body.style.overflow = ""
      }, 150)
      return () => {
        clearTimeout(timer)
        document.body.style.overflow = ""
      }
    }
    return () => {
      document.body.style.overflow = ""
    }
  }, [open])

  if (!mounted) return null

  return (
    <div
      className={cn(
        "fixed inset-0 z-50 flex items-center justify-center p-4",
        open ? "animate-in" : "animate-out"
      )}
    >
      {/* Overlay */}
      <div
        className="fixed inset-0 bg-black/50 transition-opacity"
        onClick={() => onOpenChange(false)}
      />
      {/* Content */}
      {children}
    </div>
  )
}

// ── DialogContent ──

interface DialogContentProps extends React.HTMLAttributes<HTMLDivElement> {
  onClose?: () => void
}

function DialogContent({
  className,
  children,
  onClose,
  ...props
}: DialogContentProps) {
  return (
    <div
      className={cn(
        "relative z-50 w-full max-w-lg rounded-lg border bg-background p-6 shadow-lg sm:max-w-lg",
        className
      )}
      {...props}
    >
      {children}
      {onClose && (
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}

// ── DialogHeader ──

function DialogHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex flex-col space-y-1.5 text-center sm:text-left",
        className
      )}
      {...props}
    />
  )
}

// ── DialogTitle ──

function DialogTitle({
  className,
  ...props
}: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cn(
        "text-lg font-semibold leading-none tracking-tight",
        className
      )}
      {...props}
    />
  )
}

// ── DialogDescription ──

function DialogDescription({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

// ── DialogFooter ──

function DialogFooter({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2",
        className
      )}
      {...props}
    />
  )
}

export {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
}
