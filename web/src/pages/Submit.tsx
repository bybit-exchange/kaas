import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { useT } from '@/i18n'
import { submit } from '@/api/submit'
import { ApiError } from '@/api/client'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { FileUploadZone } from '@/components/FileUploadZone'

export function Submit() {
  const t = useT()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'file' | 'url' | 'paste'>('file')

  // paste tab state
  const [pasteContent, setPasteContent] = useState('')
  const [pasteTitle, setPasteTitle] = useState('')

  // url tab state
  const [urlValue, setUrlValue] = useState('')
  const [urlTitle, setUrlTitle] = useState('')

  const [loading, setLoading] = useState(false)
  const [succeeded, setSucceeded] = useState(false)

  const isSubmitDisabled = useCallback((): boolean => {
    if (loading) return true
    if (tab === 'paste') return !pasteContent.trim()
    if (tab === 'url') return !urlValue.trim()
    return true
  }, [loading, tab, pasteContent, urlValue])

  const handleSubmit = useCallback(async () => {
    setLoading(true)
    setSucceeded(false)

    try {
      if (tab === 'paste') {
        await submit({
          source: 'paste',
          content: pasteContent,
          ...(pasteTitle.trim() ? { title: pasteTitle.trim() } : {}),
        })
      } else {
        await submit({
          source: 'url',
          url: urlValue,
          ...(urlTitle.trim() ? { title: urlTitle.trim() } : {}),
        })
      }

      toast.success(t('submit.success'))
      setSucceeded(true)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.error(t('submit.duplicate'))
      } else {
        const msg = err instanceof Error ? err.message : t('submit.errorGeneric')
        toast.error(msg)
      }
    } finally {
      setLoading(false)
    }
  }, [tab, pasteContent, pasteTitle, urlValue, urlTitle, t])

  return (
    <div className="mx-auto w-4xl p-4 sm:p-6">
      <h1 className="mb-6 text-xl font-semibold">{t('submit.title')}</h1>

      <Tabs
        value={tab}
        onValueChange={(v) => {
          setTab(v as 'file' | 'url' | 'paste')
          setSucceeded(false)
        }}
      >
        <TabsList>
          <TabsTrigger value="file">{t('submit.tabFile')}</TabsTrigger>
          <TabsTrigger value="url">{t('submit.tabUrl')}</TabsTrigger>
          <TabsTrigger value="paste">{t('submit.tabPaste')}</TabsTrigger>
        </TabsList>

        {/* File tab */}
        <TabsContent value="file">
          <div className="pt-4">
            <FileUploadZone onUploadComplete={() => setSucceeded(true)} />
          </div>
        </TabsContent>

        {/* URL tab */}
        <TabsContent value="url">
          <div className="space-y-4 pt-4">
            <div className="space-y-1.5">
              <label htmlFor="url-input" className="text-sm font-medium">
                {t('submit.urlLabel')}
              </label>
              <Input
                id="url-input"
                aria-label={t('submit.urlLabel')}
                type="url"
                placeholder={t('submit.urlPlaceholder')}
                value={urlValue}
                onChange={(e) => setUrlValue(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="url-title" className="text-sm font-medium">
                {t('submit.titleLabel')}
              </label>
              <Input
                id="url-title"
                aria-label={t('submit.titleLabel')}
                placeholder={t('submit.titleLabel')}
                value={urlTitle}
                onChange={(e) => setUrlTitle(e.target.value)}
              />
            </div>
          </div>
        </TabsContent>

        {/* Paste tab */}
        <TabsContent value="paste">
          <div className="space-y-4 pt-4">
            <div className="space-y-1.5">
              <label htmlFor="paste-content" className="text-sm font-medium">
                {t('submit.contentLabel')}
              </label>
              <textarea
                id="paste-content"
                aria-label={t('submit.contentLabel')}
                className="min-h-[160px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder={t('submit.contentLabel')}
                value={pasteContent}
                onChange={(e) => setPasteContent(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="paste-title" className="text-sm font-medium">
                {t('submit.titleLabel')}
              </label>
              <Input
                id="paste-title"
                aria-label={t('submit.titleLabel')}
                placeholder={t('submit.titleLabel')}
                value={pasteTitle}
                onChange={(e) => setPasteTitle(e.target.value)}
              />
            </div>
          </div>
        </TabsContent>
      </Tabs>

      {/* Submit button - only for paste and url tabs */}
      {tab !== 'file' && (
        <div className="mt-8 flex items-center gap-3">
          <Button onClick={handleSubmit} disabled={isSubmitDisabled()}>
            {loading ? t('submit.submitting') : t('submit.button')}
          </Button>
          {succeeded && (
            <Button variant="outline" onClick={() => navigate('/tasks')}>
              {t('submit.viewStatus')}
            </Button>
          )}
        </div>
      )}

      {/* View status button for file tab after upload */}
      {tab === 'file' && succeeded && (
        <div className="mt-8">
          <Button variant="outline" onClick={() => navigate('/tasks')}>
            {t('submit.viewStatus')}
          </Button>
        </div>
      )}
    </div>
  )
}
