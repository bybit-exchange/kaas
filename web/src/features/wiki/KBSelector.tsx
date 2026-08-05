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

interface KBSelectorProps {
  /** Bump to reload the list — a finished derive adds a knowledge base. */
  reloadKey?: number
}

/**
 * Picks which knowledge base the wiki tree and chat read from: the root KB or
 * one of its derived, topic-scoped KBs.
 *
 * Loads its own list so the page does not have to thread it down, and only
 * renders it — dropping a selection whose knowledge base is gone belongs to
 * useSyncKB, which runs on every route rather than only on this page.
 */
export function KBSelector({ reloadKey = 0 }: KBSelectorProps) {
  const t = useT()
  const kb = useKB((s) => s.kb)
  const setKB = useKB((s) => s.setKB)
  const [kbs, setKBs] = useState<DerivedKB[]>([])

  // Runs on mount and whenever reloadKey changes: the list changes when someone
  // derives a new KB, not when the reader switches between existing ones.
  useEffect(() => {
    let cancelled = false
    listDerived()
      .then(({ kbs }) => {
        if (!cancelled) setKBs(kbs)
      })
      // Keep the list we have. Blanking it would leave `value` matching no item,
      // and Radix renders nothing at all for that — the trigger would go empty
      // while the tree is still scoped to the derived KB.
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [reloadKey])

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
