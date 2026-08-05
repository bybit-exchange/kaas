import { useEffect, useState } from 'react'
import { useT } from '@/i18n'
import { listDerived, type DerivedKB } from '@/api/derived'
import { useKB } from '@/store/kb'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

// Radix Select forbids an empty item value, so the root knowledge base needs a
// sentinel of its own rather than ''.
const ROOT_VALUE = '__root__'

/**
 * Picks which knowledge base the wiki tree and chat read from: the root KB or
 * one of its derived, topic-scoped KBs.
 *
 * Loads its own list so the page does not have to thread it down. A failed load
 * leaves the current selection alone rather than dropping it: a transient blip
 * must not silently move the reader to a different corpus.
 */
export function KBSelector() {
  const t = useT()
  const kb = useKB((s) => s.kb)
  const setKB = useKB((s) => s.setKB)
  const [kbs, setKBs] = useState<DerivedKB[]>([])

  // Mount-only: the list changes when someone derives a new KB, not when the
  // reader switches between existing ones. Depending on `kb` would refetch on
  // every switch, so the stale-selection check reads the store directly instead.
  useEffect(() => {
    let cancelled = false
    listDerived()
      .then(({ kbs }) => {
        if (cancelled) return
        setKBs(kbs)
        // A persisted selection can outlive its knowledge base (deleted on
        // disk). Silently reading the root corpus under a stale label would be
        // worse than dropping the selection.
        const selected = useKB.getState().kb
        if (selected && !kbs.some((k) => k.slug === selected)) setKB(null)
      })
      .catch(() => {
        if (!cancelled) setKBs([])
      })
    return () => {
      cancelled = true
    }
  }, [setKB])

  return (
    <Select
      value={kb ?? ROOT_VALUE}
      onValueChange={(value) => setKB(value === ROOT_VALUE ? null : value)}
    >
      <SelectTrigger className="h-8 w-full text-xs" aria-label={t('wiki.kbLabel')}>
        <SelectValue placeholder={t('wiki.kbRoot')} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ROOT_VALUE}>{t('wiki.kbRoot')}</SelectItem>
        {kbs.map((k) => (
          <SelectItem key={k.slug} value={k.slug}>
            {/* The literal space keeps the option's accessible name readable —
                without it the two spans concatenate into "topic7 articles". */}
            <span className="flex items-baseline gap-2">
              <span className="truncate">{k.topic || k.slug}</span>{' '}
              <span className="shrink-0 text-xs text-muted-foreground">
                {t('wiki.kbArticleCount', { count: k.article_count })}
              </span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
