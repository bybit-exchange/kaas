import { useEffect, useState } from 'react'
import { useT } from '@/i18n'
import type { DeriveJob } from '@/api/derived'
import { listWiki, type WikiTreeNode } from '@/api/wiki'
import { StatusStageBadge } from './StatusStageBadge'
import { DeriveWikiPreviewSheet } from './DeriveWikiPreviewSheet'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/formatDate'

export interface DeriveJobDetailSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  job: DeriveJob | null
  loading: boolean
}

interface WikiArticleRow {
  path: string
  title: string
  tags: string[]
}

function flattenWikiTree(nodes: WikiTreeNode[]): WikiArticleRow[] {
  const result: WikiArticleRow[] = []
  function walk(nodes: WikiTreeNode[]) {
    for (const node of nodes) {
      if (node.isDir && node.children) {
        walk(node.children)
      } else if (!node.isDir) {
        result.push({
          path: node.path,
          title: node.title || node.name,
          tags: node.tags || [],
        })
      }
    }
  }
  walk(nodes)
  return result
}

/** Human-readable label for the select_from field. */
function selectFromLabel(t: (key: string) => string, value: string): string {
  switch (value) {
    case 'articles':
      return t('builds.selectFromArticles')
    case 'documents':
      return t('builds.selectFromDocuments')
    default:
      return t('builds.selectFromDefault')
  }
}

export function DeriveJobDetailSheet({ open, onOpenChange, job, loading }: DeriveJobDetailSheetProps) {
  const t = useT()

  // Article table state
  const [articles, setArticles] = useState<WikiArticleRow[]>([])
  const [articlesLoading, setArticlesLoading] = useState(false)
  const [articlesError, setArticlesError] = useState<string | null>(null)

  // Preview sheet state
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewPath, setPreviewPath] = useState<string | null>(null)
  const [previewTitle, setPreviewTitle] = useState('')

  // Fetch articles when job is succeeded
  useEffect(() => {
    if (job?.status !== 'succeeded') {
      setArticles([])
      setArticlesLoading(false)
      setArticlesError(null)
      return
    }

    let stale = false
    setArticlesLoading(true)
    setArticlesError(null)
    setArticles([])

    listWiki(job.slug)
      .then((res) => {
        if (stale) return
        setArticles(flattenWikiTree(res.tree))
      })
      .catch((err) => {
        if (stale) return
        setArticlesError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!stale) setArticlesLoading(false)
      })

    return () => {
      stale = true
    }
  }, [job?.id, job?.status])

  const isSucceeded = job?.status === 'succeeded'

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[50vw] min-w-[400px] flex flex-col">
        <SheetHeader>
          <SheetTitle>{t('builds.deriveDetailTitle')}</SheetTitle>
          <SheetDescription>{t('builds.deriveDetailDesc')}</SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-3/4" />
            </div>
          ) : job ? (
            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap gap-3">
                <div>
                  <span className="font-medium">{t('builds.colTopic')}: </span>
                  <span className="text-muted-foreground">{job.topic}</span>
                </div>
                <div>
                  <span className="font-medium">{t('builds.colSlug')}: </span>
                  <span className="text-muted-foreground">{job.slug}</span>
                </div>
              </div>

              <div className="flex flex-wrap gap-3">
                <div>
                  <span className="font-medium">{t('status.colStatus')}: </span>
                  <StatusStageBadge status={job.status} stage={job.stage} />
                </div>
                <div>
                  <span className="font-medium">Model: </span>
                  <span className="text-muted-foreground">{job.model || '—'}</span>
                </div>
                <div>
                  <span className="font-medium">{t('builds.colSelectFrom')}: </span>
                  <span className="text-muted-foreground">{selectFromLabel(t, job.select_from)}</span>
                </div>
              </div>

              <div className="flex flex-wrap gap-3 text-muted-foreground">
                <span>Created: {formatDate(job.created_at)}</span>
                <span>Updated: {formatDate(job.updated_at)}</span>
              </div>

              {job.error && (
                <div>
                  <p className="mb-1 font-medium text-destructive">{t('status.error')}</p>
                  <pre className="whitespace-pre-wrap break-all overflow-auto rounded bg-destructive/10 p-3 text-xs text-destructive">
                    {job.error}
                  </pre>
                </div>
              )}

              {/* Article table — only for succeeded jobs */}
              {isSucceeded && (
                <div>
                  <p className="mb-1 font-medium">{t('builds.deriveArticles')}</p>
                  {articlesLoading && (
                    <div className="space-y-2">
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-3/4" />
                    </div>
                  )}
                  {articlesError && (
                    <p className="text-sm text-destructive">{t('builds.deriveArticlesError')}</p>
                  )}
                  {!articlesLoading && !articlesError && articles.length === 0 && (
                    <p className="text-sm text-muted-foreground">{t('builds.deriveArticlesEmpty')}</p>
                  )}
                  {!articlesLoading && !articlesError && articles.length > 0 && (
                    <div className="overflow-x-auto rounded-md border">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b bg-muted/40 text-left">
                            <th className="px-4 py-3 font-medium">{t('builds.deriveColTitle')}</th>
                            <th className="px-4 py-3 font-medium">{t('builds.deriveColPath')}</th>
                            <th className="px-4 py-3 font-medium">{t('builds.deriveColTags')}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {articles.map((article) => (
                            <tr key={article.path} className="border-b last:border-0 hover:bg-muted/50">
                              <td className="px-4 py-3">
                                <button
                                  type="button"
                                  className="text-left text-primary underline-offset-4 hover:underline"
                                  onClick={() => {
                                    setPreviewPath(article.path)
                                    setPreviewTitle(article.title)
                                    setPreviewOpen(true)
                                  }}
                                >
                                  {article.title}
                                </button>
                              </td>
                              <td className="px-4 py-3 text-muted-foreground">
                                {article.path.includes('/') ? article.path.substring(0, article.path.lastIndexOf('/')) : '—'}
                              </td>
                              <td className="px-4 py-3 text-muted-foreground">
                                {article.tags.length > 0 ? article.tags.join(', ') : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {job.result !== undefined && job.result !== null && (
                <div>
                  <p className="mb-1 font-medium">{t('status.result')}</p>
                  <div className="max-h-80 overflow-auto rounded bg-muted py-3 font-mono text-xs">
                    {JSON.stringify(job.result, null, 2).split('\n').map((line, i) => (
                      <div key={i} className="flex">
                        <span className="w-8 shrink-0 select-none pr-2 text-right text-muted-foreground">{i + 1}</span>
                        <span className="min-w-0 whitespace-pre-wrap break-all pr-3">{line}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>
      </SheetContent>

      {/* Article preview sheet */}
      <DeriveWikiPreviewSheet
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        articlePath={previewPath}
        kb={job?.slug ?? ''}
        displayTitle={previewTitle}
      />
    </Sheet>
  )
}
