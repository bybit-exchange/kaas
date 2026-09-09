import { useState } from 'react'
import { useT } from '@/i18n'
import type { BuildJobDetailDTO } from '@/api/buildJobs'
import { StatusStageBadge } from './StatusStageBadge'
import { TaskDetailSheet } from './TaskDetailSheet'
import { FilePreviewSheet } from '@/components/FilePreviewSheet'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'

export interface BuildJobDetailSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  job: BuildJobDetailDTO | null
  loading: boolean
}

function formatDate(ts: number): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(ts))
  } catch {
    return String(ts)
  }
}

export function BuildJobDetailSheet({ open, onOpenChange, job, loading }: BuildJobDetailSheetProps) {
  const t = useT()

  // Nested TaskDetailSheet state
  const [taskDetailOpen, setTaskDetailOpen] = useState(false)
  const [taskDetailId, setTaskDetailId] = useState<string | null>(null)

  // FilePreviewSheet state
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewTaskId, setPreviewTaskId] = useState<string | null>(null)
  const [previewTitle, setPreviewTitle] = useState<string>('')

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[50vw] min-w-[400px] flex flex-col">
        <SheetHeader>
          <SheetTitle>{t('builds.jobDetailTitle')}</SheetTitle>
          <SheetDescription>{t('builds.jobDetailDesc')}</SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-3/4" />
            </div>
          ) : job ? (
            <div className="space-y-4 text-sm">
              {/* Job summary */}
              <div className="flex flex-wrap gap-3">
                <div>
                  <span className="font-medium">{t('builds.colSource')}: </span>
                  <span className="text-muted-foreground">{job.source}</span>
                </div>
                <div>
                  <span className="font-medium">{t('status.colStatus')}: </span>
                  <StatusStageBadge status={job.status} />
                </div>
                <div>
                  <span className="font-medium">{t('builds.colTasks')}: </span>
                  <span className="text-muted-foreground">{job.file_count}</span>
                </div>
              </div>

              <div className="flex flex-wrap gap-3 text-muted-foreground">
                <span>Created: {formatDate(job.created_at)}</span>
                <span>Updated: {formatDate(job.updated_at)}</span>
              </div>

              {job.error && (
                <div>
                  <p className="mb-1 font-medium text-destructive">{t('status.error')}</p>
                  <pre className="whitespace-pre-wrap break-all overflow-auto rounded bg-destructive/10 p-3 text-xs text-destructive">
                    {job.error}
                  </pre>
                </div>
              )}

              {/* Embedded task table */}
              {job.tasks.length > 0 && (
                <div className="overflow-x-auto rounded-md border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/40 text-left">
                        <th className="px-4 py-3 font-medium">{t('tasks.colFileTitle')}</th>
                        <th className="w-[140px] px-4 py-3 font-medium">{t('status.colStatus')}</th>
                        <th className="w-[120px] px-4 py-3 font-medium">{t('status.colAttempts')}</th>
                        <th className="w-[140px] px-4 py-3 font-medium">{t('status.colUpdated')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {job.tasks.map((task) => {
                        const displayName = task.file_title || task.title || task.source
                        return (
                          <tr
                            key={task.id}
                            className={cn(
                              'cursor-pointer border-b transition-colors last:border-0 hover:bg-muted/50',
                              task.status === 'failed' && 'border-l-4 border-destructive',
                            )}
                            onClick={() => {
                              setTaskDetailId(task.id)
                              setTaskDetailOpen(true)
                            }}
                          >
                            <td className="px-4 py-3">
                              <button
                                type="button"
                                className="text-left text-primary underline-offset-4 hover:underline"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setPreviewTaskId(task.id)
                                  setPreviewTitle(displayName)
                                  setPreviewOpen(true)
                                }}
                              >
                                {displayName}
                              </button>
                              {task.error && (
                                <span
                                  className="ml-1.5 inline-flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-[10px] text-destructive-foreground"
                                  title={task.error}
                                  aria-label="error"
                                >
                                  !
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-3">
                              <StatusStageBadge status={task.status} stage={task.stage} />
                            </td>
                            <td className="px-4 py-3 text-muted-foreground">
                              {task.attempts}/{task.max_attempts}
                            </td>
                            <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                              {formatDate(task.updated_at)}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ) : null}
        </div>
      </SheetContent>

      {/* Nested task detail sheet */}
      <TaskDetailSheet
        open={taskDetailOpen}
        onOpenChange={setTaskDetailOpen}
        taskId={taskDetailId}
      />

      {/* File preview sheet */}
      <FilePreviewSheet
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        taskId={previewTaskId}
        displayTitle={previewTitle}
      />
    </Sheet>
  )
}
