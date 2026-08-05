import { useEffect, useRef, useState } from 'react'
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
        // run going server-side, and the operator can reopen the dialog.
        if (!cancelled) setError((err as Error).message)
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

  return (
    <>
      <Button variant="outline" size="sm" className="w-full gap-1.5" onClick={() => setOpen(true)}>
        <Sparkles className="h-3.5 w-3.5" />
        {t('derive.action')}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('derive.dialogTitle')}</DialogTitle>
            <DialogDescription>{t('derive.dialogDesc')}</DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <label className="block text-sm font-medium" htmlFor="derive-topic">
              {t('derive.topicLabel')}
            </label>
            <Input
              id="derive-topic"
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

            {error && <p className="text-sm text-destructive">{error}</p>}

            {job && !terminal && (
              <p className="text-sm text-muted-foreground">
                {job.stage ? t('derive.stage', { stage: job.stage }) : t('derive.queued')}
              </p>
            )}

            {job?.status === 'failed' && (
              <div className="space-y-1">
                <p className="text-sm font-medium">{t('derive.failed')}</p>
                <p className="text-sm text-destructive">{job.error}</p>
              </div>
            )}

            {job?.status === 'succeeded' && job.result && (
              <div className="space-y-1">
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
    </>
  )
}
