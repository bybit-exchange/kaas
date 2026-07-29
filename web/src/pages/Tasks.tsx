import { useState, useEffect, useRef, useCallback } from 'react'
import { toast } from 'sonner'
import { useT } from '@/i18n'
import { listTasks, getTask, deleteTask, type TaskDTO } from '@/api/tasks'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { FilePreviewSheet } from '@/components/FilePreviewSheet'
import { Trash2, Eye, ArrowUp, ArrowDown, ArrowUpDown, RefreshCw } from 'lucide-react'

const STATUS_FILTERS = ['all', 'pending', 'running', 'succeeded', 'failed', 'cancelled'] as const
const TERMINAL_STATUSES = ['succeeded', 'failed', 'cancelled'] as const
type StatusFilter = (typeof STATUS_FILTERS)[number]

const PAGE_SIZE = 10

type SortKey = 'title' | 'file_title' | 'source' | 'status' | 'stage' | 'attempts' | 'updated_at'
type SortDir = 'asc' | 'desc'

function statusLabel(t: (key: string) => string, status: string): string {
  const key = `status.filter.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

function statusColor(status: string): string {
  switch (status) {
    case 'succeeded':
      return 'border-green-300 text-green-700 dark:border-green-700 dark:text-green-400'
    case 'failed':
      return 'border-red-300 text-red-700 dark:border-red-700 dark:text-red-400'
    case 'cancelled':
      return 'border-orange-300 text-orange-700 dark:border-orange-700 dark:text-orange-400'
    case 'running':
      return 'border-blue-300 text-blue-700 dark:border-blue-700 dark:text-blue-400'
    case 'pending':
      return 'border-yellow-300 text-yellow-700 dark:border-yellow-700 dark:text-yellow-400'
    default:
      return ''
  }
}

function stageLabel(t: (key: string) => string, stage: string): string {
  const key = `stage.${stage}`
  const translated = t(key)
  return translated === key ? stage : translated
}

function stageColor(stage: string): string {
  switch (stage) {
    case 'done':
      return 'border-green-300 text-green-700 dark:border-green-700 dark:text-green-400'
    case 'extract':
      return 'border-cyan-300 text-cyan-700 dark:border-cyan-700 dark:text-cyan-400'
    case 'pipeline':
      return 'border-violet-300 text-violet-700 dark:border-violet-700 dark:text-violet-400'
    case 'index':
      return 'border-indigo-300 text-indigo-700 dark:border-indigo-700 dark:text-indigo-400'
    case 'queued':
      return 'border-gray-300 text-gray-600 dark:border-gray-600 dark:text-gray-400'
    default:
      return ''
  }
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

export function Tasks() {
  const t = useT()
  const [tasks, setTasks] = useState<TaskDTO[]>([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const isFirstRef = useRef(true)
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [selectedTask, setSelectedTask] = useState<TaskDTO | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<TaskDTO | null>(null)
  const [deleting, setDeleting] = useState(false)

  // File preview state
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewTaskId, setPreviewTaskId] = useState<string | null>(null)
  const [previewTitle, setPreviewTitle] = useState<string>('')

  // Sort state
  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  // Search state
  const [inputValue, setInputValue] = useState('')
  const [query, setQuery] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Refresh trigger
  const [refreshCounter, setRefreshCounter] = useState(0)

  // Pagination state
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const totalPages = Math.ceil(total / PAGE_SIZE)

  // Debounce search input
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setQuery(inputValue)
      setPage(1)
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [inputValue])

  const fetchTasks = useCallback(
    async (statusFilter: StatusFilter, searchQuery: string, currentPage: number, sort?: SortKey | null, order?: SortDir) => {
      try {
        const params = {
          status: statusFilter !== 'all' ? statusFilter : undefined,
          q: searchQuery || undefined,
          sort: sort || undefined,
          order: sort ? order : undefined,
          limit: PAGE_SIZE,
          offset: (currentPage - 1) * PAGE_SIZE,
        }
        const res = await listTasks(params)
        setTasks(res.tasks)
        setTotal(res.total)
      } catch (err) {
        const msg = err instanceof Error ? err.message : t('status.fetchError')
        toast.error(msg)
      }
    },
    [t],
  )

  useEffect(() => {
    if (isFirstRef.current) {
      setInitialLoading(true)
    } else {
      setRefreshing(true)
    }
    fetchTasks(filter, query, page, sortKey, sortDir).finally(() => {
      if (isFirstRef.current) {
        setInitialLoading(false)
        isFirstRef.current = false
      } else {
        setRefreshing(false)
      }
    })
  }, [filter, query, page, sortKey, sortDir, refreshCounter, fetchTasks])

  const handleRowClick = useCallback(async (task: TaskDTO) => {
    setDialogOpen(true)
    setDetailLoading(true)
    setSelectedTask(task)
    try {
      const detail = await getTask(task.id)
      setSelectedTask(detail)
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('status.fetchError')
      toast.error(msg)
    } finally {
      setDetailLoading(false)
    }
  }, [t])

  const handleDeleteConfirm = useCallback(async () => {
    if (!deleteTarget || deleting) return
    setDeleting(true)
    try {
      await deleteTask(deleteTarget.id)
      toast.success(t('tasks.deleteSuccess'))
      setDeleteTarget(null)
      if (tasks.length === 1 && page > 1) {
        setPage(page - 1)
      } else {
        setRefreshCounter(c => c + 1)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('tasks.deleteFailed')
      toast.error(msg)
    } finally {
      setDeleting(false)
    }
  }, [deleteTarget, deleting, tasks.length, page, t])

  const toggleSort = useCallback((key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }, [sortKey])

  const handleSearch = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    setQuery(inputValue)
    setPage(1)
  }, [inputValue])

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{t('status.title')}</h1>
        <div className="flex items-center gap-3">
          {/* Status filter */}
          <Select
            value={filter}
            onValueChange={(v) => setFilter(v as StatusFilter)}
          >
            <SelectTrigger className="w-36" aria-label={t('status.filterAll')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_FILTERS.map((s) => (
                <SelectItem key={s} value={s}>
                  {t(`status.filter.${s}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Search input */}
          <Input
            className="w-48"
            placeholder={t('tasks.search')}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSearch() }}
          />

          {/* Refresh */}
          <Button size="sm" onClick={() => setRefreshCounter(c => c + 1)}>
            <RefreshCw className={cn("mr-1.5 h-4 w-4", refreshing && "animate-spin")} />
            {t('tasks.refresh')}
          </Button>
        </div>
      </div>

      {/* Table */}
      {initialLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <p className="mt-8 text-center text-muted-foreground">{t('status.empty')}</p>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-left">
                {([
                  ['file_title', t('tasks.colFileTitle')],
                  ['source', t('status.colSource')],
                  ['status', t('status.colStatus')],
                  ['stage', t('status.colStage')],
                  ['attempts', t('status.colAttempts')],
                  ['updated_at', t('status.colUpdated')],
                ] as [SortKey, string][]).map(([key, label]) => (
                  <th
                    key={key}
                    className="cursor-pointer select-none px-4 py-3 font-medium hover:bg-muted/60"
                    onClick={() => toggleSort(key)}
                  >
                    <span className="inline-flex items-center gap-1">
                      {label}
                      {sortKey === key ? (
                        sortDir === 'asc' ? <ArrowUp className="h-3.5 w-3.5" /> : <ArrowDown className="h-3.5 w-3.5" />
                      ) : (
                        <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground/50" />
                      )}
                    </span>
                  </th>
                ))}
                <th className="px-4 py-3 font-medium">{t('tasks.colActions')}</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => {
                const displayName = task.file_title || task.title || task.source
                return (
                  <tr
                    key={task.id}
                    className={cn(
                      'border-b transition-colors last:border-0 hover:bg-muted/50',
                      task.error && 'bg-destructive/5',
                    )}
                  >
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        className="text-left text-primary underline-offset-4 hover:underline"
                        onClick={() => {
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
                    <td className="px-4 py-3 text-muted-foreground">{task.source}</td>
                    <td className="px-4 py-3">
                      <Badge variant="outline" className={statusColor(task.status)}>{statusLabel(t, task.status)}</Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="outline" className={stageColor(task.stage)}>{stageLabel(t, task.stage)}</Badge>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {task.attempts}/{task.max_attempts}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{formatDate(task.updated_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs"
                          onClick={() => handleRowClick(task)}
                        >
                          <Eye className="mr-1 h-3.5 w-3.5" />
                          {t('tasks.viewDetail')}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
                          disabled={!TERMINAL_STATUSES.includes(task.status as typeof TERMINAL_STATUSES[number])}
                          onClick={() => setDeleteTarget(task)}
                        >
                          <Trash2 className="mr-1 h-3.5 w-3.5" />
                          {t('tasks.delete')}
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 0 && (
        <div className="mt-4 flex items-center justify-between">
          <span className="text-sm text-muted-foreground">
            {t('tasks.totalRecords').replace('{count}', String(total))}
          </span>
          {totalPages > 1 && (
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                {t('tasks.prevPage')}
              </Button>
              {(() => {
                const pages: (number | '...')[] = []
                if (totalPages <= 7) {
                  for (let i = 1; i <= totalPages; i++) pages.push(i)
                } else {
                  pages.push(1)
                  if (page > 3) pages.push('...')
                  for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) pages.push(i)
                  if (page < totalPages - 2) pages.push('...')
                  pages.push(totalPages)
                }
                return pages.map((p, idx) =>
                  p === '...' ? (
                    <span key={`dot-${idx}`} className="px-2 text-sm text-muted-foreground">…</span>
                  ) : (
                    <Button
                      key={p}
                      variant={p === page ? 'default' : 'outline'}
                      size="sm"
                      className="min-w-8"
                      onClick={() => setPage(p)}
                    >
                      {p}
                    </Button>
                  ),
                )
              })()}
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                {t('tasks.nextPage')}
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Detail dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{selectedTask?.title ?? t('status.detailTitle')}</DialogTitle>
          </DialogHeader>
          {detailLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-3/4" />
            </div>
          ) : selectedTask ? (
            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap gap-3">
                <div>
                  <span className="font-medium">{t('status.colStatus')}: </span>
                  <Badge variant="outline" className={statusColor(selectedTask.status)}>{statusLabel(t, selectedTask.status)}</Badge>
                </div>
                <div>
                  <span className="font-medium">{t('status.colStage')}: </span>
                  <span className="text-muted-foreground">{selectedTask.stage}</span>
                </div>
                <div>
                  <span className="font-medium">{t('status.colAttempts')}: </span>
                  <span className="text-muted-foreground">
                    {selectedTask.attempts}/{selectedTask.max_attempts}
                  </span>
                </div>
              </div>

              {selectedTask.error && (
                <div>
                  <p className="mb-1 font-medium text-destructive">{t('status.error')}</p>
                  <pre className="whitespace-pre-wrap break-all overflow-auto rounded bg-destructive/10 p-3 text-xs text-destructive">
                    {selectedTask.error}
                  </pre>
                </div>
              )}

              {selectedTask.result !== undefined && selectedTask.result !== null && (
                <div>
                  <p className="mb-1 font-medium">{t('status.result')}</p>
                  <div className="max-h-80 overflow-auto rounded bg-muted py-3 font-mono text-xs">
                    {JSON.stringify(selectedTask.result, null, 2).split('\n').map((line, i) => (
                      <div key={i} className="flex">
                        <span className="w-8 shrink-0 select-none pr-2 text-right text-muted-foreground">{i + 1}</span>
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

      {/* File preview sheet */}
      <FilePreviewSheet
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        taskId={previewTaskId}
        displayTitle={previewTitle}
      />

      {/* Delete confirmation dialog */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('tasks.deleteConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('tasks.deleteConfirmDesc')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeleteTarget(null)}>{t('chat.deleteConfirmCancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteConfirm} disabled={deleting}>{t('tasks.delete')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
