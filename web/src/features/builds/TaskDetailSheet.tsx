import { useState, useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { useT } from '@/i18n'
import { getTask, type TaskDTO } from '@/api/tasks'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { StatusStageBadge } from './StatusStageBadge'

export interface TaskDetailSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  taskId: string | null
}

export function TaskDetailSheet({ open, onOpenChange, taskId }: TaskDetailSheetProps) {
  const t = useT()
  const [task, setTask] = useState<TaskDTO | null>(null)
  const [loading, setLoading] = useState(false)

  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!open || !taskId) {
      setTask(null)
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    getTask(taskId, controller.signal)
      .then((detail) => {
        if (!controller.signal.aborted) setTask(detail)
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        const msg = err instanceof Error ? err.message : t('status.fetchError')
        toast.error(msg)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => {
      controller.abort()
    }
  }, [open, taskId, t])

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[80vw] min-w-[400px] flex flex-col">
        <SheetHeader>
          <SheetTitle>{task?.title ?? t('status.detailTitle')}</SheetTitle>
          <SheetDescription>{t('tasks.detailDesc')}</SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-3/4" />
            </div>
          ) : task ? (
            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap gap-3">
                <div>
                  <span className="font-medium">{t('status.colStatus')}: </span>
                  <StatusStageBadge status={task.status} />
                </div>
                <div>
                  <span className="font-medium">{t('status.colStage')}: </span>
                  <span className="text-muted-foreground">{task.stage}</span>
                </div>
                <div>
                  <span className="font-medium">{t('status.colAttempts')}: </span>
                  <span className="text-muted-foreground">
                    {task.attempts}/{task.max_attempts}
                  </span>
                </div>
              </div>

              {task.error && (
                <div>
                  <p className="mb-1 font-medium text-destructive">{t('status.error')}</p>
                  <pre className="whitespace-pre-wrap break-all overflow-auto rounded bg-destructive/10 p-3 text-xs text-destructive">
                    {task.error}
                  </pre>
                </div>
              )}

              {task.result !== undefined && task.result !== null && (
                <div>
                  <p className="mb-1 font-medium">{t('status.result')}</p>
                  <div className="max-h-80 overflow-auto rounded bg-muted py-3 font-mono text-xs">
                    {JSON.stringify(task.result, null, 2)
                      .split('\n')
                      .map((line, i) => (
                        <div key={i} className="flex">
                          <span className="w-8 shrink-0 select-none pr-2 text-right text-muted-foreground">
                            {i + 1}
                          </span>
                          <span className="min-w-0 whitespace-pre-wrap break-all pr-3">{line}</span>
                        </div>
                      ))}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}
