import { apiFetch } from './client'

export interface WikiTreeNode {
  name: string
  path: string
  title?: string
  isDir: boolean
  fileCount?: number
  tags?: string[]
  children?: WikiTreeNode[]
}

export interface WikiArticle {
  path: string
  title: string
  tags?: string[]
  sources?: string[]
  created?: string
  content: string
}

/** Lists the wiki tree of the root knowledge base, or of a derived one when kb is a slug. */
export async function listWiki(kb?: string | null): Promise<{ tree: WikiTreeNode[] }> {
  const res = await apiFetch(kb ? `/wiki?kb=${encodeURIComponent(kb)}` : '/wiki')
  return res.json() as Promise<{ tree: WikiTreeNode[] }>
}

export async function fetchWikiArticle(path: string, kb?: string | null): Promise<WikiArticle> {
  const query = `path=${encodeURIComponent(path)}${kb ? `&kb=${encodeURIComponent(kb)}` : ''}`
  const res = await apiFetch(`/wiki/file?${query}`)
  return res.json() as Promise<WikiArticle>
}
