import { useEffect, useRef, useState } from 'react'
import { Loader2, AlertTriangle } from 'lucide-react'
import { useT } from '@/i18n'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { fetchWikiArticle, type WikiArticle } from '@/api/wiki'

interface DeriveWikiPreviewSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  articlePath: string | null
  kb: string
  displayTitle: string
}

export function DeriveWikiPreviewSheet({ open, onOpenChange, articlePath, kb, displayTitle }: DeriveWikiPreviewSheetProps) {
  const t = useT()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [article, setArticle] = useState<WikiArticle | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!open || !articlePath) {
      setArticle(null)
      setError(null)
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)
    setArticle(null)

    fetchWikiArticle(articlePath, kb)
      .then((res) => {
        if (controller.signal.aborted) return
        setArticle(res)
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : 'Failed to load article')
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      })

    return () => {
      controller.abort()
    }
  }, [open, articlePath, kb])

  const lines = article?.content?.split('\n') ?? []

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[50vw] min-w-[400px] flex flex-col">
        <SheetHeader>
          <SheetTitle className="truncate">
            {displayTitle || t('builds.deriveArticlePreviewTitle')}
          </SheetTitle>
          <SheetDescription className="sr-only">
            {t('builds.deriveArticlePreviewDesc')}
          </SheetDescription>
          {article && (
            <div className="space-y-1">
              {article.tags && article.tags.length > 0 && (
                <p className="text-sm text-muted-foreground">
                  <span className="font-medium">Tags:</span> {article.tags.join(', ')}
                </p>
              )}
              {article.sources && article.sources.length > 0 && (
                <div className="text-sm text-muted-foreground">
                  <span className="font-medium">Sources:</span>
                  <ul className="ml-4 list-disc">
                    {article.sources.map((src) => (
                      <li key={src}>{src}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </SheetHeader>

        <div className="flex-1 overflow-auto rounded-md bg-card p-4 pl-0">
          {loading && (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              <span className="ml-2 text-sm text-muted-foreground">
                {t('builds.deriveArticlesLoading')}
              </span>
            </div>
          )}

          {error && (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
              <AlertTriangle className="h-10 w-10 mb-2" />
              <p className="text-sm">{error}</p>
            </div>
          )}

          {!loading && !error && article != null && (
            <pre className="font-mono text-sm leading-relaxed">
              {lines.map((line, idx) => (
                <div key={idx} className="flex">
                  <span className="select-none text-right text-muted-foreground min-w-[3rem] pr-2 shrink-0">
                    {idx + 1}
                  </span>
                  <span className="select-none border-r border-border pr-3 mr-3 shrink-0" />
                  <span className="whitespace-pre-wrap break-all">{line}</span>
                </div>
              ))}
            </pre>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
