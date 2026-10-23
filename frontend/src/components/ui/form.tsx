/** Form controls: Tabs, Select, Checkbox, Switch, ToggleGroup, ScrollArea, Progress. */
import { CheckIcon, ChevronDownIcon } from 'lucide-react'
import {
  Checkbox as CB,
  Progress as PR,
  ScrollArea as SA,
  Select as SE,
  Switch as SW,
  Tabs as TB,
  ToggleGroup as TG,
} from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

// ----- Tabs ------------------------------------------------------------------------------------------

export const Tabs = TB.Root

export function TabsList({ className, ...props }: ComponentProps<typeof TB.List>) {
  return (
    <TB.List
      className={cn('inline-flex h-9 items-center gap-0.5 rounded-lg bg-muted p-[3px] text-muted-foreground', className)}
      {...props}
    />
  )
}

export function TabsTrigger({ className, ...props }: ComponentProps<typeof TB.Trigger>) {
  return (
    <TB.Trigger
      className={cn(
        "inline-flex h-full items-center justify-center gap-1.5 rounded-md px-3 text-[13px] font-medium whitespace-nowrap transition-[color,background-color,box-shadow] outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm dark:data-[state=active]:bg-accent [&_svg:not([class*='size-'])]:size-3.5",
        className,
      )}
      {...props}
    />
  )
}

export function TabsContent({ className, ...props }: ComponentProps<typeof TB.Content>) {
  return <TB.Content className={cn('outline-none', className)} {...props} />
}

// ----- Select ----------------------------------------------------------------------------------------

export const Select = SE.Root
export const SelectValue = SE.Value
export const SelectGroup = SE.Group

export function SelectTrigger({ className, children, ...props }: ComponentProps<typeof SE.Trigger>) {
  return (
    <SE.Trigger
      className={cn(
        'flex h-9 w-full items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-sm whitespace-nowrap outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-50 data-[placeholder]:text-muted-foreground [&>span]:truncate',
        className,
      )}
      {...props}
    >
      {children}
      <SE.Icon asChild>
        <ChevronDownIcon className="size-4 opacity-60" />
      </SE.Icon>
    </SE.Trigger>
  )
}

export function SelectContent({ className, children, position = 'popper', ...props }: ComponentProps<typeof SE.Content>) {
  return (
    <SE.Portal>
      <SE.Content
        position={position}
        className={cn(
          'relative z-50 max-h-80 min-w-[8rem] overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-xl data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
          position === 'popper' && 'w-full min-w-[var(--radix-select-trigger-width)] data-[side=bottom]:translate-y-1',
          className,
        )}
        {...props}
      >
        <SE.Viewport className="p-1">{children}</SE.Viewport>
      </SE.Content>
    </SE.Portal>
  )
}

export function SelectItem({ className, children, ...props }: ComponentProps<typeof SE.Item>) {
  return (
    <SE.Item
      className={cn(
        'relative flex w-full cursor-default items-center gap-2 rounded-md py-1.5 pr-8 pl-2 text-sm outline-none select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-accent',
        className,
      )}
      {...props}
    >
      <span className="absolute right-2 flex size-3.5 items-center justify-center">
        <SE.ItemIndicator>
          <CheckIcon className="size-4" />
        </SE.ItemIndicator>
      </span>
      <SE.ItemText>{children}</SE.ItemText>
    </SE.Item>
  )
}

// ----- Checkbox / Switch -------------------------------------------------------------------------------

export function Checkbox({ className, ...props }: ComponentProps<typeof CB.Root>) {
  return (
    <CB.Root
      className={cn(
        'peer size-4 shrink-0 rounded-[4px] border border-input bg-card transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50 data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground',
        className,
      )}
      {...props}
    >
      <CB.Indicator className="flex items-center justify-center">
        <CheckIcon className="size-3" strokeWidth={3} />
      </CB.Indicator>
    </CB.Root>
  )
}

export function Switch({ className, ...props }: ComponentProps<typeof SW.Root>) {
  return (
    <SW.Root
      className={cn(
        'peer inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50 data-[state=checked]:bg-primary data-[state=unchecked]:bg-input',
        className,
      )}
      {...props}
    >
      <SW.Thumb className="pointer-events-none block size-4 rounded-full bg-white shadow-sm ring-0 transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0.5" />
    </SW.Root>
  )
}

// ----- ToggleGroup (segmented control) -----------------------------------------------------------------

export function Segmented({ className, ...props }: ComponentProps<typeof TG.Root>) {
  return <TG.Root className={cn('inline-flex items-center gap-0.5 rounded-lg bg-muted p-[3px]', className)} {...props} />
}

export function SegmentedItem({ className, ...props }: ComponentProps<typeof TG.Item>) {
  return (
    <TG.Item
      className={cn(
        // Selected state via aria-checked/aria-pressed: a wrapping Tooltip trigger overwrites data-state.
        "inline-flex h-7 items-center justify-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium text-muted-foreground transition-[color,background-color,box-shadow] outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-checked:bg-card aria-checked:text-foreground aria-checked:shadow-sm aria-pressed:bg-card aria-pressed:text-foreground aria-pressed:shadow-sm dark:aria-checked:bg-accent dark:aria-pressed:bg-accent [&_svg:not([class*='size-'])]:size-3.5",
        className,
      )}
      {...props}
    />
  )
}

// ----- ScrollArea ----------------------------------------------------------------------------------------

export function ScrollArea({
  className,
  children,
  viewportRef,
  viewportClassName,
  ...props
}: ComponentProps<typeof SA.Root> & { viewportRef?: React.Ref<HTMLDivElement>; viewportClassName?: string }) {
  return (
    <SA.Root className={cn('relative overflow-hidden', className)} {...props}>
      <SA.Viewport ref={viewportRef} className={cn('size-full rounded-[inherit] outline-none', viewportClassName)}>
        {children}
      </SA.Viewport>
      <SA.Scrollbar orientation="vertical" className="flex w-2 touch-none p-px transition-colors select-none">
        <SA.Thumb className="relative flex-1 rounded-full bg-foreground/15 hover:bg-foreground/25" />
      </SA.Scrollbar>
      <SA.Corner />
    </SA.Root>
  )
}

// ----- Progress ------------------------------------------------------------------------------------------

export function Progress({ className, value, indicatorClassName, ...props }: ComponentProps<typeof PR.Root> & { indicatorClassName?: string }) {
  return (
    <PR.Root className={cn('relative h-1.5 w-full overflow-hidden rounded-full bg-muted', className)} value={value} {...props}>
      <PR.Indicator
        className={cn('h-full rounded-full bg-primary transition-[width] duration-500', indicatorClassName)}
        style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }}
      />
    </PR.Root>
  )
}
