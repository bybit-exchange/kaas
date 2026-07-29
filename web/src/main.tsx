import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'sonner'
import { LangProvider } from '@/i18n'
// Import prefs store early so persisted theme class is applied to <html> on load (avoids FOUC)
import '@fontsource/orbitron/700.css'
import '@/store/prefs'
import App from './App'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LangProvider>
      <BrowserRouter>
        <App />
        <Toaster richColors />
      </BrowserRouter>
    </LangProvider>
  </StrictMode>,
)
