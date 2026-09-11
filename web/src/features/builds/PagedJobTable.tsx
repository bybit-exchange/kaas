import { useState, useEffect, useRef, useCallback, type ReactNode } from 'react'
import { toast } from 'sonner'
import { useT } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogFooter,
  AlertDialogTitle, AlertDialogDescription, AlertDialogAction, AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { Eye, Trash2, ArrowUp, ArrowDown, ArrowUpDown, RefreshCw } from 'lucide-react'

const PAGE_SIZE = 10
type SortDir = 'asc' | 'desc'

/** Describes one column in the job table. */
export interface ColumnDef<TJob, TSortKey extends string> {
  key: TSortKey
  label: string
  widthClass?: string
  render: (job: TJob) => ReactNode
}

/** Configuration for fetching a page of jobs. */
export interface FetchParams {
  status?: string
  q?: string
  sort?: string
  order?: string
  limit: number
  offset: number
}

/** The result shape returned by every list API. */
export interface PagedResult<TJob> {
  jobs: TJob[]
  total: number
}

export interface PagedJobTableProps<
  TJob extends { id: string; status: string },
  TDetail,
  TSortKey extends string,
> {
  /** Header content to render at the left of the toolbar. */
  headerLeft?: ReactNode
  /** Status filter options (including 'all'). */
  statusFilters: readonly string[]
  /** Set of statuses from which a job may be deleted. */
  deletableStatuses: Set<string>
  /** Column definitions for the table. */
  columns: ColumnDef<TJob, TSortKey>[]
  /** Fetch a page of jobs. */
  listJobs: (params: FetchParams) => Promise<PagedResult<TJob>>
  /** Fetch full detail for one job. */
  getJob: (id: string) => Promise<TDetail>
  /** Delete a job by id. */
  deleteJob: (id: string) => Promise<void>
  /**
   * Convert a list-view job to a preview detail for optimistic display.
   * Called on row click to immediately populate the detail sheet with
   * partial data while the full detail loads. If omitted, the detail
   * sheet receives null until the full detail arrives.
   */
  toPreviewDetail?: (job: TJob) => TDetail
  /** i18n keys for toast/dialog messages. */
  i18n: {
    deleteSuccess: string
    deleteFailed: string
    deleteConfirmTitle: string
    deleteConfirmDesc: string
  }
  /** Custom empty state (replaces default skeleton). */
  emptyState?: ReactNode
  /** Render the detail sheet. Receives open state and the loaded detail. */
  renderDetailSheet: (props: {
    open: boolean
    onOpenChange: (open: boolean) => void
    job: TDetail | null
    loading: boolean
  }) => ReactNode
}

export function PagedJobTable<
  TJob extends { id: string; status: string },
  TDetail,
  TSortKey extends string,
>({
  headerLeft,
  statusFilters,
  deletableStatuses,
  columns,
  listJobs,
  getJob,
  deleteJob,
  toPreviewDetail,
  i18n: i18nKeys,
  emptyState,
  renderDetailSheet,
}: PagedJobTableProps<TJob, TDetail, TSortKey>) {
  const t = useT()

  const [jobs, setJobs] = useState<TJob[]>([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const isFirstRef = useRef(true)
  const [filter, setFilter] = useState<string>('all')

  // Detail sheet state
  const [selectedJob, setSelectedJob] = useState<TDetail | null>(null)
  const [detailSheetOpen, setDetailSheetOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)

  // Delete state
  const [deleteTarget, setDeleteTarget] = useState<TJob | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Sort state
  const [sortKey, setSortKey] = useState<TSortKey | null>(null)
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

  const fetchJobs = useCallback(
    async (statusFilter: string, searchQuery: string, currentPage: number, sort?: TSortKey | null, order?: SortDir) => {
      try {
        const params: FetchParams = {
          status: statusFilter !== 'all' ? statusFilter : undefined,
          q: searchQuery || undefined,
          sort: sort || undefined,
          order: sort ? order : undefined,
          limit: PAGE_SIZE,
          offset: (currentPage - 1) * PAGE_SIZE,
        }
        const res = await listJobs(params)
        setJobs(res.jobs)
        setTotal(res.total)
      } catch (err) {
        const msg = err instanceof Error ? err.message : t('status.fetchError')
        toast.error(msg)
      }
    },
    [t, listJobs],
  )

  useEffect(() => {
    if (isFirstRef.current) {
      setInitialLoading(true)
    } else {
      setRefreshing(true)
    }
    fetchJobs(filter, query, page, sortKey, sortDir).finally(() => {
      if (isFirstRef.current) {
        setInitialLoading(false)
        isFirstRef.current = false
      } else {
        setRefreshing(false)
      }
    })
  }, [filter, query, page, sortKey, sortDir, refreshCounter, fetchJobs])

  const handleRowClick = useCallback(async (job: TJob) => {
    setDetailSheetOpen(true)
    setDetailLoading(true)
    // Show partial data immediately if a converter is provided.
    setSelectedJob(toPreviewDetail ? toPreviewDetail(job) : null)
    try {
      const detail = await getJob(job.id)
      setSelectedJob(detail)
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('status.fetchError')
      toast.error(msg)
    } finally {
      setDetailLoading(false)
    }
  }, [t, getJob, toPreviewDetail])

  const handleDeleteConfirm = useCallback(async () => {
    if (!deleteTarget || deleting) return
    setDeleting(true)
    try {
      await deleteJob(deleteTarget.id)
      toast.success(i18nKeys.deleteSuccess)
      setDeleteTarget(null)
      if (jobs.length === 1 && page > 1) {
        setPage(page - 1)
      } else {
        setRefreshCounter(c => c + 1)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : i18nKeys.deleteFailed
      toast.error(msg)
    } finally {
      setDeleting(false)
    }
  }, [deleteTarget, deleting, deleteJob, jobs.length, page, i18nKeys])

  const toggleSort = useCallback((key: TSortKey) => {
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
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 py-4">
        {headerLeft}
        <div className="flex items-center gap-3">
          {/* Status filter */}
          <Select
            value={filter}
            onValueChange={(v) => setFilter(v)}
          >
            <SelectTrigger className="w-36" aria-label={t('status.filterAll')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {statusFilters.map((s) => (
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
      ) : jobs.length === 0 ? (
        emptyState ?? (
          <div className="mt-8 text-center">
            <p className="text-muted-foreground">{t('status.empty')}</p>
          </div>
        )
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-left">
                {columns.map((col) => (
                  <th
                    key={col.key}
                    className={cn(col.widthClass, 'cursor-pointer select-none px-4 py-3 font-medium hover:bg-muted/60')}
                    onClick={() => toggleSort(col.key)}
                  >
                    <span className="inline-flex items-center gap-1">
                      {col.label}
                      {sortKey === col.key ? (
                        sortDir === 'asc' ? <ArrowUp className="h-3.5 w-3.5" /> : <ArrowDown className="h-3.5 w-3.5" />
                      ) : (
                        <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground/50" />
                      )}
                    </span>
                  </th>
                ))}
                <th className="w-[120px] px-4 py-3 font-medium">{t('tasks.colActions')}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr
                  key={job.id}
                  className={cn(
                    'border-b transition-colors last:border-0 hover:bg-muted/50',
                    job.status === 'failed' && 'border-l-4 border-l-destructive',
                  )}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={cn(
                        'px-4 py-3',
                        col.key === columns[0]?.key ? 'max-w-[260px] break-words' : 'whitespace-nowrap',
                      )}
                    >
                      {col.render(job)}
                    </td>
                  ))}
                  <td className="whitespace-nowrap px-4 py-3">
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleRowClick(job)
                        }}
                      >
                        <Eye className="mr-1 h-3.5 w-3.5" />
                        {t('tasks.viewDetail')}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
                        disabled={!deletableStatuses.has(job.status)}
                        onClick={(e) => {
                          e.stopPropagation()
                          setDeleteTarget(job)
                        }}
                      >
                        <Trash2 className="mr-1 h-3.5 w-3.5" />
                        {t('tasks.delete')}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 0 && (
        <div className="mt-4 flex items-center justify-between">
          <span className="text-sm text-muted-foreground">
            {t('tasks.totalRecords', { count: total })}
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

      {/* Detail sheet */}
      {renderDetailSheet({
        open: detailSheetOpen,
        onOpenChange: setDetailSheetOpen,
        job: selectedJob,
        loading: detailLoading,
      })}

      {/* Delete confirmation dialog */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{i18nKeys.deleteConfirmTitle}</AlertDialogTitle>
            <AlertDialogDescription>{i18nKeys.deleteConfirmDesc}</AlertDialogDescription>
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
