import { lazy, Suspense } from 'react'
import React from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import type { Components } from 'react-markdown'

const MermaidBlock = lazy(() =>
  import('./MermaidBlock').then((m) => ({ default: m.MermaidBlock })),
)

interface MarkdownArticleProps {
  content: string
}

function extractText(node: React.ReactNode): string {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractText).join('')
  if (React.isValidElement(node)) return extractText((node.props as { children?: React.ReactNode }).children)
  return ''
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .trim()
}

export function MarkdownArticle({ content }: MarkdownArticleProps) {
  const components: Components = {
    code({ className, children, ...props }) {
      const match = /language-(\w+)/.exec(className || '')
      const lang = match?.[1]

      if (lang === 'mermaid') {
        return (
          <Suspense fallback={<div className="my-4 h-32 animate-pulse rounded bg-muted" />}>
            <MermaidBlock code={String(children).trim()} />
          </Suspense>
        )
      }

      const isInline = !className
      if (isInline) {
        return (
          <code className="rounded bg-muted px-1.5 py-0.5 text-sm" {...props}>
            {children}
          </code>
        )
      }

      return (
        <code className={`${className}`} {...props}>
          {children}
        </code>
      )
    },
    pre({ children }) {
      const child = Array.isArray(children) ? children[0] : children
      const lang = (child as React.ReactElement<{ className?: string }>)?.props?.className?.replace('language-', '')
      return (
        <div className="not-prose my-3 overflow-hidden rounded-lg border border-border">
          <div className="flex h-10 items-center border-b border-border bg-muted px-4 text-xs text-muted-foreground">
            <span className="font-mono lowercase">{lang || 'plain text'}</span>
          </div>
          <pre className="m-0 overflow-x-auto rounded-none border-none bg-background font-mono text-[0.8125rem] leading-[1.7] px-4 py-3.5">
            {children}
          </pre>
        </div>
      )
    },
    table({ children }) {
      return (
        <div className="my-4 overflow-x-auto">
          <table className="w-full border-collapse border text-sm">{children}</table>
        </div>
      )
    },
    th({ children }) {
      return <th className="border bg-muted/50 px-3 py-2 text-left font-medium">{children}</th>
    },
    td({ children }) {
      return <td className="border px-3 py-2">{children}</td>
    },
    a({ href, children }) {
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary underline hover:no-underline"
        >
          {children}
        </a>
      )
    },
    h2({ children }) {
      const id = slugify(extractText(children))
      return (
        <h2 id={id} className="mt-8 mb-4 scroll-mt-20 text-xl font-semibold">
          {children}
        </h2>
      )
    },
    h3({ children }) {
      const id = slugify(extractText(children))
      return (
        <h3 id={id} className="mt-6 mb-3 scroll-mt-20 text-lg font-medium">
          {children}
        </h3>
      )
    },
  }

  const cleaned = content.replace(
    /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
    (_, text, display) => `**${display || text}**`,
  )

  return (
    <article className="prose prose-neutral dark:prose-invert max-w-none">
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {cleaned}
      </Markdown>
    </article>
  )
}
