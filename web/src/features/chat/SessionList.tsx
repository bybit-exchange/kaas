import { useState, useRef, useEffect, useMemo } from 'react'
import { Plus, Trash2, Pencil } from 'lucide-react'
import type { Session } from '@/api/sessions'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { cn } from '@/lib/cn'
import { groupSessionsByDate, type DateGroup } from '@/lib/groupSessionsByDate'
import { useT } from '@/i18n'

export interface SessionListProps {
  sessions: Session[]
  activeSessionId?: string
  onNewChat: () => void
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onRename: (id: string, title: string) => void
}

const GROUP_LABEL_KEYS: Record<DateGroup, string> = {
  today: 'chat.dateGroupToday',
  yesterday: 'chat.dateGroupYesterday',
  last7days: 'chat.dateGroupLast7Days',
  last30days: 'chat.dateGroupLast30Days',
  older: 'chat.dateGroupOlder',
}

export function SessionList({
  sessions,
  activeSessionId,
  onNewChat,
  onSelect,
  onDelete,
  onRename,
}: SessionListProps) {
  const t = useT()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)
  const groupedSessions = useMemo(() => groupSessionsByDate(sessions), [sessions])
  const inputRef = useRef<HTMLInputElement>(null)
  const committedRef = useRef(false)
  const composingRef = useRef(false)

  useEffect(() => {
    if (editingId && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editingId])

  function startEditing(sid: string, currentTitle: string) {
    committedRef.current = false
    setEditingId(sid)
    setEditValue(currentTitle || t('chat.defaultSessionTitle'))
  }

  function commitEdit() {
    if (committedRef.current) return
    committedRef.current = true
    if (editingId && editValue.trim()) {
      onRename(editingId, editValue.trim())
    }
    setEditingId(null)
    setEditValue('')
  }

  function cancelEdit() {
    setEditingId(null)
    setEditValue('')
  }

  return (
    <div className="flex h-full w-64 flex-col border-r bg-muted/20">
      <div className="px-2 py-4">
        <Button onClick={onNewChat} className="w-full gap-2">
          <Plus className="h-5 w-5" aria-hidden="true" />
          {t('chat.newChat')}
        </Button>
      </div>
      <ScrollArea className="flex-1">
        <div className="px-2 py-1">
          {groupedSessions.map((group) => (
            <div key={group.key} className="mb-2">
              <div className="px-3 py-1.5 text-xs font-medium text-muted-foreground">
                {t(GROUP_LABEL_KEYS[group.key])}
              </div>
              <div className="space-y-1">
                {group.sessions.map((session) => {
                  const sid = String(session.id)
                  const isEditing = editingId === sid
                  return (
                    <div
                      key={sid}
                      role="button"
                      tabIndex={0}
                      aria-current={activeSessionId === sid ? 'page' : undefined}
                      className={cn(
                        'group flex min-h-[44px] cursor-pointer items-center justify-between rounded-md px-3 py-2 text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
                        activeSessionId === sid && 'bg-accent font-medium',
                      )}
                      onClick={() => {
                        if (!isEditing) onSelect(sid)
                      }}
                      onKeyDown={(e) => {
                        if (isEditing) return
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          onSelect(sid)
                        }
                      }}
                      onDoubleClick={(e) => {
                        e.stopPropagation()
                        startEditing(sid, session.title)
                      }}
                    >
                      {isEditing ? (
                        <input
                          ref={inputRef}
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onBlur={commitEdit}
                          onCompositionStart={() => {
                            composingRef.current = true
                          }}
                          onCompositionEnd={() => {
                            composingRef.current = false
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && !composingRef.current) {
                              e.preventDefault()
                              commitEdit()
                            }
                            if (e.key === 'Escape') {
                              cancelEdit()
                            }
                            e.stopPropagation()
                          }}
                          onClick={(e) => e.stopPropagation()}
                          className="min-w-0 flex-1 rounded border bg-background px-1.5 py-0.5 text-sm outline-none focus:ring-1 focus:ring-ring"
                        />
                      ) : (
                        <span className="truncate">
                          {session.title || t('chat.defaultSessionTitle')}
                        </span>
                      )}
                      <div className="flex shrink-0 items-center gap-0.5">
                        {!isEditing && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                            onClick={(e) => {
                              e.stopPropagation()
                              startEditing(sid, session.title)
                            }}
                          >
                            <Pencil className="h-3 w-3" aria-hidden="true" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                          onClick={(e) => {
                            e.stopPropagation()
                            setPendingDeleteId(sid)
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                        </Button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>
      <AlertDialog
        open={pendingDeleteId !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDeleteId(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('chat.deleteConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('chat.deleteConfirmDesc')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('chat.deleteConfirmCancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingDeleteId) onDelete(pendingDeleteId)
                setPendingDeleteId(null)
              }}
            >
              {t('chat.deleteConfirmAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
