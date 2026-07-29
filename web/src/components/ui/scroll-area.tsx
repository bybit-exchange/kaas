import { cn } from '@/lib/cn'

export function ScrollArea({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('relative overflow-hidden', className)} {...props}>
      <div className="h-full w-full overflow-auto">{children}</div>
    </div>
  )
}
