import { useT } from '@/i18n'
import type { ChatSource } from './StreamHandler'
import { Badge } from '@/components/ui/badge'

interface SourcePanelProps {
  sources: ChatSource[]
}

/**
 * Build the /wiki route href for a source path.
 *
 * Chat sources are kb-root relative (`wiki/concept/x.md`) while the wiki route
 * and /api/wiki/file are both rooted at the wiki dir, so the leading segment
 * has to go or the request resolves to <kb>/wiki/wiki/... and 404s. Paths from
 * the wiki tree endpoint already arrive without it.
 */
function wikiHref(path: string): string {
  return `/wiki/${path.replace(/^wiki\//, '')}`
}

export function SourcePanel({ sources }: SourcePanelProps) {
  const t = useT()
  if (sources.length === 0) return null

  return (
    <div className="mt-3 border-t pt-3" aria-label={t('chat.sources')}>
      <p className="mb-2 text-xs font-medium text-muted-foreground">{t('chat.sources')}</p>
      <div className="space-y-1.5">
        {sources.map((source, idx) => (
          <div
            key={source.path}
            id={`source-${idx + 1}`}
            className="flex items-center gap-2 text-sm rounded-md py-0.5 transition-colors duration-300"
          >
            <Badge
              variant="outline"
              className="shrink-0 font-mono text-xs min-w-[1.5rem] justify-center"
            >
              {idx + 1}
            </Badge>
            <a
              href={wikiHref(source.path)}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={source.title}
              className="inline-flex items-center gap-1 text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-sm min-w-0 truncate"
            >
              {source.title}
            </a>
          </div>
        ))}
      </div>
    </div>
  )
}
