import { useT } from '@/i18n'
import { listBuildJobs, deleteBuildJob, getBuildJob, type BuildJobDTO, type BuildJobDetailDTO } from '@/api/buildJobs'
import { formatDate } from '@/lib/formatDate'
import { StatusStageBadge } from './StatusStageBadge'
import { BuildJobDetailSheet } from './BuildJobDetailSheet'
import { PagedJobTable, type ColumnDef } from './PagedJobTable'

const STATUS_FILTERS = ['all', 'pending', 'running', 'succeeded', 'failed', 'partial'] as const
const DELETABLE_STATUSES = new Set(['succeeded', 'failed', 'partial'])
type SortKey = 'title' | 'source' | 'file_count' | 'status' | 'updated_at'

export interface BuildJobsTabProps {
  headerLeft?: React.ReactNode
}

export function BuildJobsTab({ headerLeft }: BuildJobsTabProps) {
  const t = useT()

  const columns: ColumnDef<BuildJobDTO, SortKey>[] = [
    { key: 'title', label: t('status.colTitle'), render: (j) => j.title },
    { key: 'source', label: t('builds.colSource'), render: (j) => <span className="text-muted-foreground">{j.source}</span> },
    { key: 'file_count', label: t('builds.colTasks'), widthClass: 'w-[100px]', render: (j) => <span className="text-muted-foreground">{j.file_count}</span> },
    { key: 'status', label: t('status.colStatus'), widthClass: 'w-[160px]', render: (j) => <StatusStageBadge status={j.status} /> },
    { key: 'updated_at', label: t('status.colUpdated'), widthClass: 'w-[160px]', render: (j) => <span className="text-muted-foreground">{formatDate(j.updated_at)}</span> },
  ]

  return (
    <PagedJobTable<BuildJobDTO, BuildJobDetailDTO, SortKey>
      headerLeft={headerLeft}
      statusFilters={STATUS_FILTERS}
      deletableStatuses={DELETABLE_STATUSES}
      columns={columns}
      listJobs={listBuildJobs}
      getJob={getBuildJob}
      deleteJob={deleteBuildJob}
      toPreviewDetail={(job) => ({ ...job, tasks: [] })}
      i18n={{
        deleteSuccess: t('builds.jobDeleteSuccess'),
        deleteFailed: t('builds.jobDeleteFailed'),
        deleteConfirmTitle: t('builds.jobDeleteConfirmTitle'),
        deleteConfirmDesc: t('builds.jobDeleteConfirmDesc'),
      }}
      emptyState={
        <div className="mt-8 text-center">
          <p className="text-muted-foreground">{t('builds.jobsEmpty')}</p>
          <p className="mt-2 text-sm text-muted-foreground">{t('builds.jobsEmptyAction')}</p>
        </div>
      }
      renderDetailSheet={(props) => <BuildJobDetailSheet {...props} />}
    />
  )
}
