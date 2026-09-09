import { useState, useEffect, useCallback } from 'react'
import { toast } from 'sonner'
import { useT } from '@/i18n'
import { getTask, type TaskDTO } from '@/api/tasks'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { statusColor } from './StatusStageBadge'

/** Translate a status key to its display label. */
function statusLabel(t: (key: string) => string, status: string): string {
  const key = `status.filter.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

export interface TaskDetailDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  taskId: string | null
}

export function TaskDetailDialog({ open, onOpenChange, taskId }: TaskDetailDialogProps) {
  const t = useT()
  const [task, setTask] = useState<TaskDTO | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchDetail = useCallback(
    async (id: string) => {
      setLoading(true)
      try {
        const detail = await getTask(id)
        setTask(detail)
      } catch (err) {
        const msg = err instanceof Error ? err.message : t('status.fetchError')
        toast.error(msg)
      } finally {
        setLoading(false)
      }
    },
    [t],
  )

  useEffect(() => {
    if (open && taskId) {
      fetchDetail(taskId)
    }
    if (!open) {
      setTask(null)
    }
  }, [open, taskId, fetchDetail])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{task?.title ?? t('status.detailTitle')}</DialogTitle>
        </DialogHeader>
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
                <Badge variant="outline" className={statusColor(task.status)}>
                  {statusLabel(t, task.status)}
                </Badge>
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
      </DialogContent>
    </Dialog>
  )
}
