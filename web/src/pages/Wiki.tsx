import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Calendar, Loader2, Search, Tag, X } from 'lucide-react'
import { useT } from '@/i18n'
import { listWiki, fetchWikiArticle, type WikiTreeNode, type WikiArticle } from '@/api/wiki'
import { ApiError } from '@/api/client'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { MarkdownArticle } from '@/features/wiki/MarkdownArticle'
import { TableOfContents } from '@/features/wiki/TableOfContents'
import { FileTree } from '@/features/wiki/FileTree'

export function Wiki() {
  const t = useT()
  const params = useParams()
  const path = params['*'] || null

  const [searchQuery, setSearchQuery] = useState('')
  const [tree, setTree] = useState<WikiTreeNode[]>([])
  const [indexLoading, setIndexLoading] = useState(true)
  const [article, setArticle] = useState<WikiArticle | null>(null)
  const [articleLoading, setArticleLoading] = useState(false)
  const [articleError, setArticleError] = useState<string | null>(null)
  const [showAllTags, setShowAllTags] = useState(false)
  const [showSources, setShowSources] = useState(false)

  // Load index list
  useEffect(() => {
    setIndexLoading(true)
    listWiki()
      .then(({ tree }) => setTree(tree))
      .catch(() => setTree([]))
      .finally(() => setIndexLoading(false))
  }, [])

  // Load article when path changes
  useEffect(() => {
    if (!path) {
      setArticle(null)
      setArticleError(null)
      return
    }

    setArticleLoading(true)
    setArticleError(null)
    setArticle(null)
    setShowAllTags(false)
    setShowSources(false)

    fetchWikiArticle(path)
      .then(setArticle)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setArticleError(t('wiki.notFound'))
        } else {
          setArticleError(t('wiki.errorLoad'))
        }
      })
      .finally(() => setArticleLoading(false))
  }, [path, t])


  const pathParts = path?.split('/') ?? []

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left index list */}
      <aside className="w-80 shrink-0 border-r bg-muted/30">
        <div className="flex h-14 items-center px-4">
          <h2 className="text-sm font-semibold">{t('wiki.indexTitle')}</h2>
        </div>
        <Separator />
        <div className="p-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('wiki.search')}
              className="pl-8 pr-8"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
        <ScrollArea className="h-[calc(100%-3.5rem-3rem)]">
          <nav className="p-3">
            {indexLoading ? (
              <div className="space-y-2 p-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : (
              <FileTree nodes={tree} activePath={path} searchQuery={searchQuery} />
            )}
          </nav>
        </ScrollArea>
      </aside>

      {/* Main content area */}
      <div className="flex min-w-0 flex-1 overflow-hidden">
        <ScrollArea className="flex-1">
          <div className="mx-auto max-w-4xl px-6 py-8">
            {/* Article meta */}
            {path && article && !articleLoading && (
              <div className="mb-8">
                <nav className="mb-2 text-xs text-muted-foreground" aria-label="Breadcrumb">
                  {pathParts.slice(0, -1).map((part, i) => (
                    <span key={i}>
                      {i > 0 && <span className="mx-1">/</span>}
                      <span>{part}</span>
                    </span>
                  ))}
                </nav>
                <h1 className="text-2xl font-bold tracking-tight">{article.title}</h1>
                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
                  {article.created && (
                    <span className="inline-flex items-center gap-1">
                      <Calendar className="h-3.5 w-3.5" />
                      {article.created}
                    </span>
                  )}
                  {article.tags && article.tags.length > 0 && (
                    <span className="inline-flex flex-wrap items-center gap-1">
                      <Tag className="h-3.5 w-3.5 shrink-0" />
                      {(showAllTags ? article.tags : article.tags.slice(0, 5)).map((tag) => (
                        <span key={tag} className="whitespace-nowrap rounded bg-muted px-1.5 py-0.5 text-xs">{tag}</span>
                      ))}
                      {article.tags.length > 5 && (
                        <button
                          onClick={() => setShowAllTags(!showAllTags)}
                          className="whitespace-nowrap text-xs text-primary hover:underline"
                        >
                          {showAllTags ? 'collapse' : `+${article.tags.length - 5} more`}
                        </button>
                      )}
                    </span>
                  )}
                  {article.sources && article.sources.length > 0 && (
                    <button
                      onClick={() => setShowSources(true)}
                      className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                    >
                      {article.sources.length} source{article.sources.length > 1 ? 's' : ''}
                    </button>
                  )}
                </div>
                <Separator className="mt-4" />
              </div>
            )}

            {/* States */}
            {!path && (
              <div className="flex flex-col items-center justify-center py-32 text-center">
                <p className="text-muted-foreground">{t('wiki.selectArticle')}</p>
              </div>
            )}

            {path && articleLoading && (
              <div className="flex items-center justify-center py-32">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                <span className="ml-2 text-sm text-muted-foreground">{t('wiki.loading')}</span>
              </div>
            )}

            {path && articleError && (
              <div className="py-16 text-center">
                <p className="text-lg font-medium">{articleError}</p>
              </div>
            )}

            {article && !articleLoading && (
              <MarkdownArticle content={article.content} />
            )}
          </div>
        </ScrollArea>

        {/* TOC sidebar */}
        {article && !articleLoading && (
          <aside className="hidden w-80 shrink-0 border-l xl:block">
            <div className="sticky top-0 p-4">
              <TableOfContents content={article.content} />
            </div>
          </aside>
        )}
      </div>

      {/* Sources dialog */}
      <Dialog open={showSources} onOpenChange={setShowSources}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Sources</DialogTitle>
            <DialogDescription>
              {article?.sources?.length ?? 0} source file{(article?.sources?.length ?? 0) > 1 ? 's' : ''} contributed to this article.
            </DialogDescription>
          </DialogHeader>
          <ul className="max-h-64 space-y-1 overflow-y-auto text-sm">
            {article?.sources?.map((src) => (
              <li key={src} className="truncate rounded bg-muted px-3 py-2 font-mono text-xs">
                {src}
              </li>
            ))}
          </ul>
        </DialogContent>
      </Dialog>
    </div>
  )
}
