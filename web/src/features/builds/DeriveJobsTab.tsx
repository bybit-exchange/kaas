import { Link } from 'react-router-dom'
import { useT } from '@/i18n'
import { listDeriveJobs, deleteDeriveJob, getDeriveJob, type DeriveJob } from '@/api/derived'
import { formatDate } from '@/lib/formatDate'
import { StatusStageBadge } from './StatusStageBadge'
import { DeriveJobDetailSheet } from './DeriveJobDetailSheet'
import { PagedJobTable, type ColumnDef } from './PagedJobTable'

const STATUS_FILTERS = ['all', 'pending', 'running', 'succeeded', 'failed'] as const
const DELETABLE_STATUSES = new Set(['succeeded', 'failed'])
type SortKey = 'topic' | 'slug' | 'status' | 'select_from' | 'updated_at'

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

export interface DeriveJobsTabProps {
  headerLeft?: React.ReactNode
}

export function DeriveJobsTab({ headerLeft }: DeriveJobsTabProps) {
  const t = useT()

  const columns: ColumnDef<DeriveJob, SortKey>[] = [
    { key: 'topic', label: t('builds.colTopic'), render: (j) => j.topic },
    { key: 'slug', label: t('builds.colSlug'), render: (j) => <span className="text-muted-foreground">{j.slug}</span> },
    { key: 'status', label: t('status.colStatus'), widthClass: 'w-[140px]', render: (j) => <StatusStageBadge status={j.status} stage={j.stage} /> },
    { key: 'select_from', label: t('builds.colSelectFrom'), widthClass: 'w-[100px]', render: (j) => <span className="text-muted-foreground">{selectFromTableLabel(t, j.select_from)}</span> },
    { key: 'updated_at', label: t('status.colUpdated'), widthClass: 'w-[140px]', render: (j) => <span className="text-muted-foreground">{formatDate(j.updated_at)}</span> },
  ]

  return (
    <PagedJobTable<DeriveJob, DeriveJob, SortKey>
      headerLeft={headerLeft}
      statusFilters={STATUS_FILTERS}
      deletableStatuses={DELETABLE_STATUSES}
      columns={columns}
      listJobs={listDeriveJobs}
      getJob={getDeriveJob}
      deleteJob={deleteDeriveJob}
      toPreviewDetail={(job) => job}
      i18n={{
        deleteSuccess: t('builds.deriveDeleteSuccess'),
        deleteFailed: t('builds.deriveDeleteFailed'),
        deleteConfirmTitle: t('builds.deriveDeleteConfirmTitle'),
        deleteConfirmDesc: t('builds.deriveDeleteConfirmDesc'),
      }}
      emptyState={
        <div className="mt-8 text-center">
          <p className="text-muted-foreground">{t('builds.deriveEmpty')}</p>
          <Link to="/wiki" className="mt-2 inline-block text-primary underline-offset-4 hover:underline">
            {t('builds.deriveEmptyAction')}
          </Link>
        </div>
      }
      renderDetailSheet={(props) => <DeriveJobDetailSheet {...props} />}
    />
  )
}
