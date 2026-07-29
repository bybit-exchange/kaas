import { useEffect, useState } from 'react'
import { fetchUploadConfig, DEFAULT_UPLOAD_CONFIG, type UploadConfig } from '@/api/upload-config'

export function useUploadConfig(): UploadConfig {
  const [config, setConfig] = useState<UploadConfig>(DEFAULT_UPLOAD_CONFIG)

  useEffect(() => {
    let cancelled = false
    fetchUploadConfig()
      .then((c) => { if (!cancelled) setConfig(c) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  return config
}
