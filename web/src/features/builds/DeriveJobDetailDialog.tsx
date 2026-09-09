import { useT } from '@/i18n'
import type { DeriveJob } from '@/api/derived'
import { StatusStageBadge } from './StatusStageBadge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'

export interface DeriveJobDetailDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  job: DeriveJob | null
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

/** Human-readable label for the select_from field in the detail dialog. */
function selectFromLabel(t: (key: string) => string, value: string): string {
  switch (value) {
    case 'articles':
      return t('builds.selectFromArticles')
    case 'documents':
      return t('builds.selectFromDocuments')
    default:
      return t('builds.selectFromDefault')
  }
}

export function DeriveJobDetailDialog({ open, onOpenChange, job, loading }: DeriveJobDetailDialogProps) {
  const t = useT()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('builds.deriveDetailTitle')}</DialogTitle>
        </DialogHeader>
        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-3/4" />
          </div>
        ) : job ? (
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap gap-3">
              <div>
                <span className="font-medium">{t('builds.colTopic')}: </span>
                <span className="text-muted-foreground">{job.topic}</span>
              </div>
              <div>
                <span className="font-medium">{t('builds.colSlug')}: </span>
                <span className="text-muted-foreground">{job.slug}</span>
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <div>
                <span className="font-medium">{t('status.colStatus')}: </span>
                <StatusStageBadge status={job.status} stage={job.stage} />
              </div>
              <div>
                <span className="font-medium">Model: </span>
                <span className="text-muted-foreground">{job.model || '—'}</span>
              </div>
              <div>
                <span className="font-medium">{t('builds.colSelectFrom')}: </span>
                <span className="text-muted-foreground">{selectFromLabel(t, job.select_from)}</span>
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

            {job.result !== undefined && job.result !== null && (
              <div>
                <p className="mb-1 font-medium">{t('status.result')}</p>
                <div className="max-h-80 overflow-auto rounded bg-muted py-3 font-mono text-xs">
                  {JSON.stringify(job.result, null, 2).split('\n').map((line, i) => (
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
  )
}
