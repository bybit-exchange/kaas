import { createContext, useContext, useState } from 'react'
import { cn } from '@/lib/cn'

const TabsContext = createContext<{ value: string; onValueChange: (v: string) => void }>({
  value: '',
  onValueChange: () => {},
})

export function Tabs({
  defaultValue,
  value: controlledValue,
  onValueChange,
  className,
  children,
  ...props
}: {
  defaultValue?: string
  value?: string
  onValueChange?: (v: string) => void
} & React.HTMLAttributes<HTMLDivElement>) {
  const [internal, setInternal] = useState(defaultValue ?? '')
  const value = controlledValue ?? internal
  const setValue = onValueChange ?? setInternal

  return (
    <TabsContext.Provider value={{ value, onValueChange: setValue }}>
      <div className={className} {...props}>{children}</div>
    </TabsContext.Provider>
  )
}

export function TabsList({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'inline-flex h-9 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground',
        className,
      )}
      {...props}
    />
  )
}

export function TabsTrigger({
  value,
  className,
  ...props
}: { value: string } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const ctx = useContext(TabsContext)
  const active = ctx.value === value

  return (
    <button
      type="button"
      className={cn(
        'inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium ring-offset-background transition-all',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        active && 'bg-background text-foreground shadow',
        className,
      )}
      onClick={() => ctx.onValueChange(value)}
      {...props}
    />
  )
}

export function TabsContent({
  value,
  className,
  ...props
}: { value: string } & React.HTMLAttributes<HTMLDivElement>) {
  const ctx = useContext(TabsContext)
  if (ctx.value !== value) return null
  return <div className={cn('mt-4', className)} {...props} />
}
