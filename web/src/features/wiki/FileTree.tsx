import { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ChevronRight,
  ChevronDown,
  Folder,
  FolderOpen,
  FileText,
} from 'lucide-react'
import { useT } from '@/i18n'
import type { WikiTreeNode } from '@/api/wiki'

interface FileTreeProps {
  nodes: WikiTreeNode[]
  activePath?: string | null
  searchQuery?: string
}

function collectDirPaths(nodes: WikiTreeNode[]): string[] {
  const paths: string[] = []
  for (const node of nodes) {
    if (node.isDir) {
      paths.push(node.path)
      if (node.children) {
        paths.push(...collectDirPaths(node.children))
      }
    }
  }
  return paths
}

function collectAllFiles(nodes: WikiTreeNode[]): WikiTreeNode[] {
  const files: WikiTreeNode[] = []
  for (const node of nodes) {
    if (node.isDir) {
      if (node.children) {
        files.push(...collectAllFiles(node.children))
      }
    } else {
      files.push(node)
    }
  }
  return files
}

function matchesQuery(node: WikiTreeNode, query: string): boolean {
  const q = query.toLowerCase()
  if ((node.title ?? node.name).toLowerCase().includes(q)) return true
  if (node.path.toLowerCase().includes(q)) return true
  if (node.tags?.some((tag) => tag.toLowerCase().includes(q))) return true
  return false
}

export function FileTree({ nodes, activePath, searchQuery }: FileTreeProps) {
  const t = useT()
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(collectDirPaths(nodes)))

  useEffect(() => {
    setExpanded((prev) => {
      if (prev.size > 0) return prev
      return new Set(collectDirPaths(nodes))
    })
  }, [nodes])

  const trimmedQuery = (searchQuery ?? '').trim()
  const deferredQuery = useDeferredValue(trimmedQuery)

  const filteredFiles = useMemo(() => {
    if (!deferredQuery) return null
    const allFiles = collectAllFiles(nodes)
    return allFiles.filter((file) => matchesQuery(file, deferredQuery))
  }, [nodes, deferredQuery])

  function toggleDir(dirPath: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(dirPath)) {
        next.delete(dirPath)
      } else {
        next.add(dirPath)
      }
      return next
    })
  }

  if (filteredFiles !== null) {
    if (filteredFiles.length === 0) {
      return (
        <p className="px-2 py-4 text-center text-sm text-muted-foreground">
          {t('wiki.searchEmpty')}
        </p>
      )
    }
    return (
      <ul className="space-y-0.5 text-sm">
        {filteredFiles.map((node) => (
          <li key={node.path}>
            <FileNode node={node} depth={0} activePath={activePath ?? null} />
          </li>
        ))}
      </ul>
    )
  }

  return (
    <nav aria-label="file tree">
      <TreeNodeList
        nodes={nodes}
        depth={0}
        activePath={activePath ?? null}
        expanded={expanded}
        toggleDir={toggleDir}
      />
    </nav>
  )
}

interface TreeNodeListProps {
  nodes: WikiTreeNode[]
  depth: number
  activePath: string | null
  expanded: Set<string>
  toggleDir: (dirPath: string) => void
}

function TreeNodeList({ nodes, depth, activePath, expanded, toggleDir }: TreeNodeListProps) {
  return (
    <ul className="space-y-0.5 text-sm">
      {nodes.map((node) => (
        <li key={node.path}>
          {node.isDir ? (
            <DirNode
              node={node}
              depth={depth}
              activePath={activePath}
              expanded={expanded}
              toggleDir={toggleDir}
            />
          ) : (
            <FileNode node={node} depth={depth} activePath={activePath} />
          )}
        </li>
      ))}
    </ul>
  )
}

interface DirNodeProps {
  node: WikiTreeNode
  depth: number
  activePath: string | null
  expanded: Set<string>
  toggleDir: (dirPath: string) => void
}

function DirNode({ node, depth, activePath, expanded, toggleDir }: DirNodeProps) {
  const isExpanded = expanded.has(node.path)

  return (
    <>
      <button
        type="button"
        onClick={() => toggleDir(node.path)}
        className="flex w-full items-center gap-1 rounded px-2 py-1 text-left hover:bg-muted"
        style={{ paddingLeft: `${depth * 12}px` }}
      >
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        {isExpanded ? (
          <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
        ) : (
          <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <span className="truncate">{node.name}</span>
        {node.fileCount != null && (
          <span className="ml-auto shrink-0 rounded bg-muted px-1.5 text-xs text-muted-foreground">
            {node.fileCount}
          </span>
        )}
      </button>
      {isExpanded && node.children && (
        <TreeNodeList
          nodes={node.children}
          depth={depth + 1}
          activePath={activePath}
          expanded={expanded}
          toggleDir={toggleDir}
        />
      )}
    </>
  )
}

interface FileNodeProps {
  node: WikiTreeNode
  depth: number
  activePath: string | null
}

function FileNode({ node, depth, activePath }: FileNodeProps) {
  const isActive = activePath === node.path

  return (
    <Link
      to={`/wiki/${node.path.split('/').map(encodeURIComponent).join('/')}`}
      className={`flex items-center gap-1 rounded px-2 py-1 hover:bg-muted ${
        isActive ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground'
      }`}
      style={{ paddingLeft: `${depth * 12}px` }}
    >
      <FileText className="h-4 w-4 shrink-0" />
      <span className="truncate">{node.title ?? node.name}</span>
    </Link>
  )
}
