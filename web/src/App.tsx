import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { AppLayout } from '@/layouts/AppLayout'
import { Chat } from '@/pages/Chat'
import { PageSpinner } from '@/components/ui/page-spinner'

const Wiki = lazy(() => import('@/pages/Wiki').then(m => ({ default: m.Wiki })))
const Submit = lazy(() => import('@/pages/Submit').then(m => ({ default: m.Submit })))
const Builds = lazy(() => import('@/pages/Builds').then(m => ({ default: m.Builds })))

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="chat/:sessionId?" element={<Chat />} />
        <Route path="submit" element={<Suspense fallback={<PageSpinner />}><Submit /></Suspense>} />
        <Route path="wiki/*" element={<Suspense fallback={<PageSpinner />}><Wiki /></Suspense>} />
        <Route path="builds/:tab?" element={<Suspense fallback={<PageSpinner />}><Builds /></Suspense>} />
        <Route path="tasks" element={<Navigate to="/builds/tasks" replace />} />
        <Route path="status" element={<Navigate to="/builds/tasks" replace />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Route>
    </Routes>
  )
}
