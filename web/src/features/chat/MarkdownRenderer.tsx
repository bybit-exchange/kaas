import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import type { Components } from 'react-markdown'
import { CitationMarker } from './CitationMarker'

// Pattern: [digits] NOT followed by ( so markdown links stay intact.
const CITATION_RE = /\[(\d+)\](?!\()/g

// ---------------------------------------------------------------------------
// Minimal local types — avoids importing 'unified' or 'mdast' as hard deps.
// ---------------------------------------------------------------------------

interface MdastTextNode {
  type: 'text'
  value: string
}

interface CitationNode {
  type: 'citation'
  data: {
    hName: string
    hProperties: { 'data-index': string }
  }
  children: []
}

// A parent node has a children array; we only need a loose shape here.
interface MdastParent {
  type: string
  children: Array<MdastTextNode | CitationNode | MdastParent | { type: string }>
}

/**
 * Remark plugin that walks mdast `text` nodes and splits any `[N]` citation
 * markers out as custom `citation` nodes.  mdast-util-to-hast honours
 * `data.hName` / `data.hProperties`, so each citation node becomes a
 * `<cite-marker data-index="N">` hast element — no raw HTML needed.
 *
 * The function signature is intentionally typed as `() => (tree: unknown) => void`
 * to avoid importing `Plugin` / `Root` from 'unified' / 'mdast'.
 */
function remarkCitations() {
  return (tree: unknown) => {
    visitText(tree as MdastParent)
  }
}

/** Recursively walk the mdast tree and expand text nodes that contain [N]. */
function visitText(node: MdastParent) {
  const newChildren: MdastParent['children'] = []

  for (const child of node.children) {
    if (child.type === 'text') {
      const expanded = expandTextNode(child as MdastTextNode)
      newChildren.push(...expanded)
    } else {
      // Recurse into block/inline containers.
      if ('children' in child) {
        visitText(child as MdastParent)
      }
      newChildren.push(child)
    }
  }

  node.children = newChildren
}

/**
 * Split a text node on [N] patterns and return a mix of text nodes and
 * citation nodes.
 */
function expandTextNode(node: MdastTextNode): Array<MdastTextNode | CitationNode> {
  const value = node.value
  CITATION_RE.lastIndex = 0

  const result: Array<MdastTextNode | CitationNode> = []
  let last = 0
  let m: RegExpExecArray | null

  while ((m = CITATION_RE.exec(value)) !== null) {
    if (m.index > last) {
      result.push({ type: 'text', value: value.slice(last, m.index) })
    }
    result.push({
      type: 'citation',
      data: {
        hName: 'cite-marker',
        hProperties: { 'data-index': m[1] },
      },
      children: [],
    })
    last = m.index + m[0].length
  }

  if (last < value.length) {
    result.push({ type: 'text', value: value.slice(last) })
  }

  // No citations found — return the original node unchanged.
  if (result.length === 0) {
    return [node]
  }

  return result
}

// ---------------------------------------------------------------------------
// Wiki link helpers — exported for unit testing.
// ---------------------------------------------------------------------------

/**
 * Detect whether a href points to an internal wiki page.
 * Matches: /wiki/..., /wiki?path=..., wiki/..., ./wiki/..., ./path (relative article paths).
 */
export function isInternalWikiLink(href: string | undefined): boolean {
  if (!href) return false
  if (href.startsWith('/wiki/') || href.startsWith('/wiki?')) return true
  if (href.startsWith('wiki/') && !href.includes('://')) return true
  // LLM generates "./path" relative links (see chat-with-sources prompt)
  if (href.startsWith('./') && !href.includes('://')) return true
  return false
}

/**
 * Normalize a wiki href to a /wiki/{path} route path.
 */
export function resolveWikiPath(href: string): string {
  // /wiki?path=team/guide.md → /wiki/team/guide.md
  if (href.startsWith('/wiki?')) {
    const params = new URLSearchParams(href.slice(href.indexOf('?')))
    const path = params.get('path') ?? ''
    return `/wiki/${path}`
  }
  // /wiki/... — already in canonical form.
  if (href.startsWith('/wiki/')) return href
  // ./wiki/path → /wiki/path
  if (href.startsWith('./wiki/')) return href.slice(1)
  // ./path (relative article path from LLM) → /wiki/path
  if (href.startsWith('./')) return `/wiki/${href.slice(2)}`
  // wiki/relative → /wiki/relative
  if (href.startsWith('wiki/')) return `/${href}`
  return href
}

interface MarkdownRendererProps {
  content: string
  onCitationClick?: (index: number) => void
}

export function MarkdownRenderer({ content, onCitationClick }: MarkdownRendererProps) {
  // Components map: react-markdown passes unknown custom elements through when
  // they appear in the hast. We cast to `Components` with an intersection to
  // allow the 'cite-marker' key without touching react-markdown's internal types.
  const components = {
    table({ children }: { children?: React.ReactNode }) {
      return (
        <div className="overflow-x-auto my-4">
          <table>{children}</table>
        </div>
      )
    },
    a({ href, children, ...rest }: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
      if (isInternalWikiLink(href)) {
        const resolved = resolveWikiPath(href!)
        return (
          <a
            href={resolved}
            target="_blank"
            rel="noopener noreferrer"
            {...rest}
          >
            {children}
          </a>
        )
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
          {children}
        </a>
      )
    },
    // Produced by the remark plugin via hName/hProperties — NO raw HTML.
    'cite-marker': (props: Record<string, unknown>) => (
      <CitationMarker
        index={Number(props['data-index'])}
        onClick={onCitationClick ?? (() => {})}
      />
    ),
  } as Components

  return (
    <div className="prose prose-neutral dark:prose-invert max-w-none text-sm prose-hr:my-4">
      <Markdown
        remarkPlugins={[remarkGfm, remarkCitations]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {content}
      </Markdown>
    </div>
  )
}
