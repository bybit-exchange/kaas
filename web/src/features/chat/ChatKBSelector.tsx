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

interface ChatKBSelectorProps {
  /** Called after the selected KB changes. */
  onChange?: () => void
}

/**
 * KB picker for the chat sidebar. Loads derived KBs via listDerived() and
 * reads/writes chatKB / setChatKB from the KB store so the Chat page can scope
 * sessions and RAG to a specific knowledge base independently of the Wiki page.
 */
export function ChatKBSelector({ onChange }: ChatKBSelectorProps) {
  const t = useT()
  const chatKB = useKB((s) => s.chatKB)
  const setChatKB = useKB((s) => s.setChatKB)
  const [kbs, setKBs] = useState<DerivedKB[]>([])

  useEffect(() => {
    let cancelled = false
    listDerived()
      .then(({ kbs }) => {
        if (!cancelled) setKBs(kbs)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const handleChange = (value: string) => {
    setChatKB(value === ROOT_VALUE ? null : value)
    onChange?.()
  }

  return (
    <Select value={chatKB ?? ROOT_VALUE} onValueChange={handleChange}>
      <SelectTrigger className="h-8 w-full text-xs" aria-label={t('chat.kbLabel')}>
        <SelectValue placeholder={t('wiki.kbRoot')} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ROOT_VALUE}>{t('wiki.kbRoot')}</SelectItem>
        {kbs.map((k) => (
          <SelectItem key={k.slug} value={k.slug}>
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
