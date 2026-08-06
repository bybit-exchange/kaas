import { useEffect, useId, useRef, useState } from 'react'
import { Loader2, Sparkles } from 'lucide-react'
import { useT } from '@/i18n'
import { getDeriveJob, startDerive, type DeriveJob } from '@/api/derived'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

const POLL_MS = 2000

interface DeriveDialogProps {
  /** Called with the new slug once a derive succeeds, so the KB list can reload. */
  onDerived?: (slug: string) => void
}

/**
 * Starts a derive and follows its job to a terminal status.
 *
 * No volume gate here: the HTTP path is asynchronous, so there is nothing to
 * prompt for mid-run (spec H5). The dialog's own copy is where the operator is
 * told this costs money, and the actual cost is reported when the job finishes.
 */
export function DeriveDialog({ onDerived }: DeriveDialogProps) {
  const t = useT()
  const topicId = useId()
  const [open, setOpen] = useState(false)
  const [topic, setTopic] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [job, setJob] = useState<DeriveJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const announced = useRef<string | null>(null)

  const terminal = job?.status === 'succeeded' || job?.status === 'failed'
  const running = Boolean(jobId) && !terminal

  useEffect(() => {
    if (!jobId || terminal) return
    let cancelled = false

    const poll = async () => {
      try {
        const next = await getDeriveJob(jobId)
        if (cancelled) return
        setJob(next)
        if (next.status !== 'succeeded' && next.status !== 'failed') {
          timer.current = setTimeout(() => void poll(), POLL_MS)
        }
      } catch (err) {
        // Stop following the job rather than retrying: a broken poll leaves the
        // run going server-side. Dropping the id is what makes the form usable
        // again — keeping it would hold `running` true forever, since this
        // effect only re-runs when the id or terminality changes. The last
        // status goes too: once we have stopped following the job, showing its
        // stage next to the error would claim progress we can no longer see.
        if (!cancelled) {
          setError((err as Error).message)
          setJobId(null)
          setJob(null)
        }
      }
    }
    void poll()

    return () => {
      cancelled = true
      if (timer.current) clearTimeout(timer.current)
    }
  }, [jobId, terminal])

  // Announced from an effect, not from the poll, so a re-render cannot fire it
  // twice for the same job.
  useEffect(() => {
    if (job?.status !== 'succeeded' || announced.current === job.id) return
    announced.current = job.id
    onDerived?.(job.slug)
  }, [job, onDerived])

  async function onStart() {
    const wanted = topic.trim()
    if (!wanted) return
    setStarting(true)
    setError(null)
    setJob(null)
    setJobId(null)
    try {
      const { job_id } = await startDerive({ topic: wanted })
      setJobId(job_id)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setStarting(false)
    }
  }

  function onOpenChange(next: boolean) {
    setOpen(next)
    // Reopening should offer a fresh form rather than the previous run's
    // numbers. Only once nothing is in flight: closing mid-run keeps following
    // the job, so its progress must survive. The id goes with the job — leaving
    // it behind would make the effect see a non-terminal job and resume polling
    // a run that is already over.
    if (!next && !running) {
      setJobId(null)
      setJob(null)
      setError(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="w-full gap-1.5">
          <Sparkles className="h-3.5 w-3.5" />
          {t('derive.action')}
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('derive.dialogTitle')}</DialogTitle>
          <DialogDescription>{t('derive.dialogDesc')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <label className="block text-sm font-medium" htmlFor={topicId}>
            {t('derive.topicLabel')}
          </label>
          <Input
            id={topicId}
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder={t('derive.topicPlaceholder')}
            disabled={running}
          />
          <Button
            onClick={() => void onStart()}
            disabled={starting || running || !topic.trim()}
          >
            {(starting || running) && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('derive.start')}
          </Button>

          {/* These arrive long after the click, so they are live regions: an
              operator who tabbed away is otherwise never told. */}
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

          {job && !terminal && (
            <p role="status" className="text-sm text-muted-foreground">
              {job.stage ? t('derive.stage', { stage: job.stage }) : t('derive.queued')}
            </p>
          )}

          {job?.status === 'failed' && (
            <div role="alert" className="space-y-1">
              <p className="text-sm font-medium">{t('derive.failed')}</p>
              <p className="text-sm text-destructive">{job.error}</p>
            </div>
          )}

          {job?.status === 'succeeded' && job.result && (
            <div role="status" className="space-y-1">
              <p className="text-sm font-medium">{t('derive.doneTitle')}</p>
              <p className="text-sm text-muted-foreground">
                {t('derive.summary', {
                  documents: job.result.documents,
                  offtopic: job.result.offtopic,
                })}
              </p>
              <p className="text-sm text-muted-foreground">
                {t('derive.cost', {
                  cost: (job.result.cost?.total_cost_usd ?? 0).toFixed(4),
                })}
              </p>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
