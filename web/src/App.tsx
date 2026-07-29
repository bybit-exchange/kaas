import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { AppLayout } from '@/layouts/AppLayout'
import { Chat } from '@/pages/Chat'
import { PageSpinner } from '@/components/ui/page-spinner'

const Wiki = lazy(() => import('@/pages/Wiki').then(m => ({ default: m.Wiki })))
const Submit = lazy(() => import('@/pages/Submit').then(m => ({ default: m.Submit })))
const Tasks = lazy(() => import('@/pages/Tasks').then(m => ({ default: m.Tasks })))

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="chat/:sessionId?" element={<Chat />} />
        <Route path="submit" element={<Suspense fallback={<PageSpinner />}><Submit /></Suspense>} />
        <Route path="wiki/*" element={<Suspense fallback={<PageSpinner />}><Wiki /></Suspense>} />
        <Route path="tasks" element={<Suspense fallback={<PageSpinner />}><Tasks /></Suspense>} />
        <Route path="status" element={<Navigate to="/tasks" replace />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Route>
    </Routes>
  )
}
