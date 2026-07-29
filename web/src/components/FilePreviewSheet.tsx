import { useEffect, useRef, useState } from 'react'
import { Loader2, AlertTriangle } from 'lucide-react'
import { useT } from '@/i18n'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { getTaskContent } from '@/api/tasks'

interface FilePreviewSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  taskId: string | null
  displayTitle?: string
}

export function FilePreviewSheet({ open, onOpenChange, taskId, displayTitle }: FilePreviewSheetProps) {
  const t = useT()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [content, setContent] = useState<string | null>(null)
  const [truncated, setTruncated] = useState(false)

  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!open || !taskId) {
      setContent(null)
      setError(null)
      setTruncated(false)
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)
    setContent(null)

    getTaskContent(taskId, controller.signal)
      .then((res) => {
        if (controller.signal.aborted) return
        setContent(res.content)
        setTruncated(res.truncated)
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        if (err instanceof Error && err.message.includes('404')) {
          setError('notfound')
        } else {
          setError('generic')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      })

    return () => {
      controller.abort()
    }
  }, [open, taskId])

  const lines = content?.split('\n') ?? []

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[50vw] min-w-[400px] flex flex-col">
        <SheetHeader>
          <SheetTitle className="truncate">
            {displayTitle || t('tasks.filePreviewTitle')}
          </SheetTitle>
          {content != null && (
            <p className="text-sm text-muted-foreground">
              {t('tasks.filePreviewLines').replace('{count}', String(lines.length))}
            </p>
          )}
        </SheetHeader>

        <div className="flex-1 overflow-auto rounded-md bg-card p-4 pl-0">
          {loading && (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              <span className="ml-2 text-sm text-muted-foreground">
                {t('tasks.filePreviewLoading')}
              </span>
            </div>
          )}

          {error && (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
              <AlertTriangle className="h-10 w-10 mb-2" />
              <p className="text-sm">{t('tasks.filePreviewError')}</p>
            </div>
          )}

          {!loading && !error && content != null && (
            <pre className="font-mono text-sm leading-relaxed">
              {lines.map((line, idx) => (
                <div key={idx} className="flex">
                  <span className="select-none text-right text-muted-foreground min-w-[3rem] pr-2 shrink-0">
                    {idx + 1}
                  </span>
                  <span className="select-none border-r border-border pr-3 mr-3 shrink-0" />
                  <span className="whitespace-pre-wrap break-all">{line}</span>
                </div>
              ))}
            </pre>
          )}
        </div>

        {truncated && !loading && !error && (
          <div className="mt-2 rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2 text-sm text-yellow-800 dark:border-yellow-700 dark:bg-yellow-950 dark:text-yellow-200">
            {t('tasks.filePreviewTruncated')}
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
