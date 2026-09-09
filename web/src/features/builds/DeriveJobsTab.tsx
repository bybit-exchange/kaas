import { useState, useEffect, useRef, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { useT } from '@/i18n'
import { listDeriveJobs, deleteDeriveJob, getDeriveJob, type DeriveJob } from '@/api/derived'
import { StatusStageBadge } from './StatusStageBadge'
import { DeriveJobDetailDialog } from './DeriveJobDetailDialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
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
import { Trash2, Eye, ArrowUp, ArrowDown, ArrowUpDown, RefreshCw } from 'lucide-react'

/** Derive jobs have no cancelled status. */
const STATUS_FILTERS = ['all', 'pending', 'running', 'succeeded', 'failed'] as const
type StatusFilter = (typeof STATUS_FILTERS)[number]

/** Only succeeded and failed jobs can be deleted. */
const DELETABLE_STATUSES = new Set(['succeeded', 'failed'])

const PAGE_SIZE = 10

type SortKey = 'topic' | 'slug' | 'status' | 'select_from' | 'updated_at'
type SortDir = 'asc' | 'desc'

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

/** Human-readable label for the select_from column in the table. */
function selectFromTableLabel(t: (key: string) => string, value: string): string {
  switch (value) {
    case 'articles':
      return t('builds.selectFromArticles')
    case 'documents':
      return t('builds.selectFromDocuments')
    default:
      return '—'
  }
}

export function DeriveJobsTab() {
  const t = useT()
  const [jobs, setJobs] = useState<DeriveJob[]>([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const isFirstRef = useRef(true)
  const [filter, setFilter] = useState<StatusFilter>('all')

  // Detail dialog state
  const [selectedJob, setSelectedJob] = useState<DeriveJob | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)

  // Delete state
  const [deleteTarget, setDeleteTarget] = useState<DeriveJob | null>(null)
  const [deleting, setDeleting] = useState(false)

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

  const fetchJobs = useCallback(
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
        const res = await listDeriveJobs(params)
        setJobs(res.jobs)
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
    fetchJobs(filter, query, page, sortKey, sortDir).finally(() => {
      if (isFirstRef.current) {
        setInitialLoading(false)
        isFirstRef.current = false
      } else {
        setRefreshing(false)
      }
    })
  }, [filter, query, page, sortKey, sortDir, refreshCounter, fetchJobs])

  const handleRowClick = useCallback(async (job: DeriveJob) => {
    setDialogOpen(true)
    setDetailLoading(true)
    setSelectedJob(job)
    try {
      const detail = await getDeriveJob(job.id)
      setSelectedJob(detail)
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
      await deleteDeriveJob(deleteTarget.id)
      toast.success(t('builds.deriveDeleteSuccess'))
      setDeleteTarget(null)
      if (jobs.length === 1 && page > 1) {
        setPage(page - 1)
      } else {
        setRefreshCounter(c => c + 1)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('builds.deriveDeleteFailed')
      toast.error(msg)
    } finally {
      setDeleting(false)
    }
  }, [deleteTarget, deleting, jobs.length, page, t])

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
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
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
      ) : jobs.length === 0 ? (
        <div className="mt-8 text-center">
          <p className="text-muted-foreground">{t('builds.deriveEmpty')}</p>
          <Link to="/wiki" className="mt-2 inline-block text-primary underline-offset-4 hover:underline">
            {t('builds.deriveEmptyAction')}
          </Link>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-left">
                {([
                  ['topic', t('builds.colTopic')],
                  ['slug', t('builds.colSlug')],
                  ['status', t('status.colStatus')],
                  ['select_from', t('builds.colSelectFrom')],
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
              {jobs.map((job) => (
                <tr
                  key={job.id}
                  className={cn(
                    'border-b transition-colors last:border-0 hover:bg-muted/50',
                    job.status === 'failed' && 'border-l-4 border-l-destructive',
                  )}
                >
                  <td className="px-4 py-3">{job.topic}</td>
                  <td className="px-4 py-3 text-muted-foreground">{job.slug}</td>
                  <td className="px-4 py-3">
                    <StatusStageBadge status={job.status} stage={job.stage} />
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {selectFromTableLabel(t, job.select_from)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{formatDate(job.updated_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        onClick={() => handleRowClick(job)}
                      >
                        <Eye className="mr-1 h-3.5 w-3.5" />
                        {t('tasks.viewDetail')}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
                        disabled={!DELETABLE_STATUSES.has(job.status)}
                        onClick={() => setDeleteTarget(job)}
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

      {/* Detail dialog */}
      <DeriveJobDetailDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        job={selectedJob}
        loading={detailLoading}
      />

      {/* Delete confirmation dialog */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('builds.deriveDeleteConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('builds.deriveDeleteConfirmDesc')}</AlertDialogDescription>
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
