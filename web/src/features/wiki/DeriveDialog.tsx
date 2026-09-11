import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { Loader2, Sparkles } from 'lucide-react'
import { useT } from '@/i18n'
import { startDerive, type SelectFrom } from '@/api/derived'
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

/**
 * The catalog the form shows selected initially, which is also the engine's own
 * default. Kept as a constant because onStart compares against it: the request
 * omits select_from while it holds, so "absent means engine default" is the one
 * rule every layer follows rather than the UI inventing a value of its own.
 */
const DEFAULT_SELECT_FROM: SelectFrom = 'articles'

/**
 * Starts a derive job and links the user to the Builds page for monitoring.
 *
 * No polling here — the Builds page handles job tracking. The dialog's role is
 * to collect topic + select_from, start the job, and point the user to /builds/derive.
 */
export function DeriveDialog() {
  const t = useT()
  const topicId = useId()
  const selectFromId = useId()
  const [open, setOpen] = useState(false)
  const [topic, setTopic] = useState('')
  const [selectFrom, setSelectFrom] = useState<SelectFrom>(DEFAULT_SELECT_FROM)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [started, setStarted] = useState(false)

  async function onStart() {
    const wanted = topic.trim()
    if (!wanted) return
    setStarting(true)
    setError(null)
    try {
      await startDerive({
        topic: wanted,
        ...(selectFrom === DEFAULT_SELECT_FROM ? {} : { select_from: selectFrom }),
      })
      setStarted(true)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setStarting(false)
    }
  }

  function onOpenChange(next: boolean) {
    setOpen(next)
    if (!next) {
      setError(null)
      setStarted(false)
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
            disabled={started}
          />

          {/* Native radios rather than the Select used elsewhere: two mutually
              exclusive choices that each need a line of explanation read better
              side by side than behind a closed dropdown, and a radio group is
              keyboard- and screen-reader-navigable without any extra wiring. */}
          <fieldset disabled={started} className="space-y-2">
            <legend className="text-sm font-medium">{t('derive.selectFromLabel')}</legend>
            {(
              [
                ['articles', 'derive.selectFromArticles', 'derive.selectFromArticlesHint'],
                ['documents', 'derive.selectFromDocuments', 'derive.selectFromDocumentsHint'],
              ] as const
            ).map(([value, labelKey, hintKey]) => (
              <label
                key={value}
                htmlFor={`${selectFromId}-${value}`}
                className="flex gap-2 text-sm"
              >
                <input
                  id={`${selectFromId}-${value}`}
                  type="radio"
                  name={selectFromId}
                  className="mt-1 shrink-0"
                  value={value}
                  checked={selectFrom === value}
                  onChange={() => setSelectFrom(value)}
                />
                <span>
                  <span className="font-medium">{t(labelKey)}</span>
                  <span className="block text-xs text-muted-foreground">{t(hintKey)}</span>
                </span>
              </label>
            ))}
          </fieldset>

          {!started && (
            <Button
              onClick={() => void onStart()}
              disabled={starting || !topic.trim()}
            >
              {starting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('derive.start')}
            </Button>
          )}

          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

          {started && (
            <div role="status" className="space-y-2">
              <p className="text-sm font-medium">{t('derive.jobStarted')}</p>
              <Link
                to="/builds/derive"
                className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
              >
                {t('derive.viewInBuilds')} →
              </Link>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
