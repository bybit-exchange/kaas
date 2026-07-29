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

export async function listWiki(): Promise<{ tree: WikiTreeNode[] }> {
  const res = await apiFetch('/wiki')
  return res.json() as Promise<{ tree: WikiTreeNode[] }>
}

export async function fetchWikiArticle(path: string): Promise<WikiArticle> {
  const res = await apiFetch(`/wiki/file?path=${encodeURIComponent(path)}`)
  return res.json() as Promise<WikiArticle>
}
