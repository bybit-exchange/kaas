import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { Loader2, Upload, X } from 'lucide-react'
import { useT } from '@/i18n'
import { Button } from '@/components/ui/button'
import { submitFiles, type SubmitFilesResult } from '@/api/submit'
import { useUploadConfig } from '@/hooks/useUploadConfig'

interface FileUploadZoneProps {
  onUploadComplete?: (result: SubmitFilesResult) => void
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function FileUploadZone({ onUploadComplete }: FileUploadZoneProps) {
  const t = useT()
  const config = useUploadConfig()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)

  const validateAndAdd = (fileList: File[]) => {
    const currentCount = selectedFiles.length
    if (currentCount + fileList.length > config.maxFilesPerUpload) {
      toast.error(t('submit.file.tooManyFiles', { max: config.maxFilesPerUpload }))
      return
    }

    const valid: File[] = []
    for (const file of fileList) {
      const ext = '.' + (file.name.split('.').pop()?.toLowerCase() ?? '')
      if (!config.allowedExtensions.includes(ext)) {
        toast.error(t('submit.file.invalidExtension', { name: file.name }))
        continue
      }
      if (ext === '.zip') {
        if (file.size > config.maxZipFileSize) {
          toast.error(t('submit.file.zipTooLarge', { name: file.name }))
          continue
        }
      } else {
        if (file.size > config.maxFileSize) {
          toast.error(t('submit.file.fileTooLarge', { name: file.name }))
          continue
        }
      }
      valid.push(file)
    }

    if (valid.length > 0) {
      setSelectedFiles((prev) => [...prev, ...valid])
    }
  }

  const handleRemoveFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const handleClear = () => {
    setSelectedFiles([])
  }

  const handleUpload = async () => {
    if (selectedFiles.length === 0) return
    setUploading(true)
    try {
      const result = await submitFiles(selectedFiles)
      const successCount = result.uploaded.length
      const total = successCount + result.failed.length
      if (successCount > 0) {
        toast.success(t('submit.file.uploadSuccess', { success: successCount, total }))
      }
      for (const f of result.failed) {
        toast.error(`${f.name}: ${f.reason}`)
      }
      setSelectedFiles([])
      onUploadComplete?.(result)
    } catch (err) {
      const message = err instanceof Error ? err.message : undefined
      toast.error(message || t('submit.file.uploadError'))
    } finally {
      setUploading(false)
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
    const droppedFiles = Array.from(e.dataTransfer.files)
    if (droppedFiles.length > 0) {
      validateAndAdd(droppedFiles)
    }
  }

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length > 0) {
      validateAndAdd(files)
    }
    e.target.value = ''
  }

  const openFilePicker = () => {
    if (!uploading) fileInputRef.current?.click()
  }

  // Uploading state
  if (uploading) {
    return (
      <div className="flex min-h-[160px] flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted-foreground/25 pointer-events-none opacity-60">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        <p className="mt-2 text-sm text-muted-foreground">{t('submit.file.uploading')}</p>
      </div>
    )
  }

  // Preview state
  if (selectedFiles.length > 0) {
    return (
      <div className="rounded-lg border-2 border-dashed border-muted-foreground/25 p-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-sm font-medium">
            {t('submit.file.selectedCount', { count: selectedFiles.length })}
          </span>
          <button
            type="button"
            className="text-sm text-primary hover:underline"
            onClick={openFilePicker}
          >
            {t('submit.file.addMore')}
          </button>
        </div>

        <div className="max-h-[240px] space-y-1 overflow-y-auto">
          {selectedFiles.map((file, index) => (
            <div
              key={`${file.name}-${index}`}
              className="flex items-center justify-between rounded px-2 py-1 hover:bg-accent"
            >
              <span className="truncate text-sm">{file.name}</span>
              <div className="flex shrink-0 items-center gap-2">
                <span className="text-xs text-muted-foreground">{formatSize(file.size)}</span>
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground"
                  onClick={() => handleRemoveFile(index)}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-3 flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={handleClear}>
            {t('submit.file.clear')}
          </Button>
          <Button size="sm" onClick={handleUpload}>
            {t('submit.file.uploadBtn', { count: selectedFiles.length })}
          </Button>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          multiple
          accept={config.allowedExtensions.join(',')}
          onChange={handleFileInputChange}
        />
      </div>
    )
  }

  // Idle state
  return (
    <div
      className={`flex min-h-[160px] cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed transition-colors ${
        dragOver
          ? 'border-primary bg-accent'
          : 'border-muted-foreground/25 hover:border-muted-foreground/50'
      }`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={openFilePicker}
    >
      <Upload className="h-8 w-8 text-muted-foreground" />
      <p className="mt-2 text-sm text-muted-foreground">{t('submit.file.dropzone')}</p>
      <p className="mt-1 text-xs text-muted-foreground/70">
        {t('submit.file.maxSize', { fileSize: formatSize(config.maxFileSize), zipSize: formatSize(config.maxZipFileSize) })} | {t('submit.file.allowedTypes', { types: config.allowedExtensions.join(' ') })}
      </p>
      <p className="mt-0.5 text-xs text-muted-foreground/70">{t('submit.file.zipHint')}</p>
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        multiple
        accept={config.allowedExtensions.join(',')}
        onChange={handleFileInputChange}
      />
    </div>
  )
}
