import { useEffect, useState } from 'react'
import { useT } from '@/i18n'

interface TocItem {
  id: string
  text: string
  level: number
}

interface TableOfContentsProps {
  content: string
}

export function TableOfContents({ content }: TableOfContentsProps) {
  const t = useT()
  const [activeId, setActiveId] = useState<string>('')

  const headings = extractHeadings(content)

  // Depend on `content` (stable string) rather than `headings` (new array ref
  // each render) to avoid re-subscribing the observer on every parent re-render.
  useEffect(() => {
    const items = extractHeadings(content)
    if (items.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting)
        if (visible.length > 0) {
          setActiveId(visible[0].target.id)
        }
      },
      { rootMargin: '-80px 0px -60% 0px', threshold: 0 },
    )

    items.forEach(({ id }) => {
      const el = document.getElementById(id)
      if (el) observer.observe(el)
    })

    return () => observer.disconnect()
  }, [content])

  if (headings.length === 0) return null

  return (
    <nav aria-label={t('wiki.tocLabel')}>
      <h4 className="mb-3 text-sm font-medium text-muted-foreground">{t('wiki.toc')}</h4>
      <ul className="space-y-1 text-sm">
        {headings.map(({ id, text, level }) => (
          <li key={id} style={{ paddingLeft: `${(level - 2) * 12}px` }}>
            <a
              href={`#${id}`}
              onClick={(e) => {
                e.preventDefault()
                document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
              }}
              className={`block truncate rounded px-2 py-1 transition-colors hover:bg-muted ${
                activeId === id ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground'
              }`}
            >
              {text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}

function extractHeadings(markdown: string): TocItem[] {
  const headings: TocItem[] = []
  const lines = markdown.split('\n')
  for (const line of lines) {
    const match = /^(#{2,3})\s+(.+)$/.exec(line)
    if (match) {
      const level = match[1].length
      const text = match[2].replace(/\*\*([^*]+)\*\*/g, '$1')
      const id = text
        .toLowerCase()
        .replace(/[^\w\s-]/g, '')
        .replace(/\s+/g, '-')
        .replace(/-+/g, '-')
        .trim()
      headings.push({ id, text, level })
    }
  }
  return headings
}
