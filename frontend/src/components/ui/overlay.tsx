/** Dialog, AlertDialog, Sheet, Tooltip, Popover, DropdownMenu (Radix). */
import { XIcon } from 'lucide-react'
import { AlertDialog as AD, Dialog as D, DropdownMenu as DM, Popover as PP, Tooltip as TT } from 'radix-ui'
import type { ComponentProps, ReactNode } from 'react'

import { cn } from '@/lib/utils'

import { buttonVariants } from './button'

const overlayCls =
  'fixed inset-0 z-50 bg-black/45 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0'

// ----- Dialog ----------------------------------------------------------------------------------------

export const Dialog = D.Root
export const DialogTrigger = D.Trigger
export const DialogClose = D.Close

export function DialogContent({
  className,
  children,
  hideClose,
  ...props
}: ComponentProps<typeof D.Content> & { hideClose?: boolean }) {
  return (
    <D.Portal>
      <D.Overlay className={overlayCls} />
      <D.Content
        className={cn(
          'fixed top-1/2 left-1/2 z-50 grid max-h-[calc(100vh-2rem)] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-xl border bg-popover p-6 text-popover-foreground shadow-2xl outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-[0.97] data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-[0.97]',
          className,
        )}
        {...props}
      >
        {children}
        {!hideClose && (
          <D.Close className="absolute top-4 right-4 rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
            <XIcon className="size-4" />
            <span className="sr-only">닫기</span>
          </D.Close>
        )}
      </D.Content>
    </D.Portal>
  )
}

export function DialogHeader({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1.5 pr-6', className)} {...props} />
}

export function DialogFooter({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)} {...props} />
}

export function DialogTitle({ className, ...props }: ComponentProps<typeof D.Title>) {
  return <D.Title className={cn('text-base font-semibold tracking-tight', className)} {...props} />
}

export function DialogDescription({ className, ...props }: ComponentProps<typeof D.Description>) {
  return <D.Description className={cn('text-sm text-muted-foreground', className)} {...props} />
}

// ----- AlertDialog -----------------------------------------------------------------------------------

export const AlertDialog = AD.Root
export const AlertDialogTrigger = AD.Trigger

export function AlertDialogContent({ className, ...props }: ComponentProps<typeof AD.Content>) {
  return (
    <AD.Portal>
      <AD.Overlay className={overlayCls} />
      <AD.Content
        className={cn(
          'fixed top-1/2 left-1/2 z-50 grid w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 gap-4 rounded-xl border bg-popover p-6 text-popover-foreground shadow-2xl data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-[0.97] data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
          className,
        )}
        {...props}
      />
    </AD.Portal>
  )
}

export const AlertDialogHeader = DialogHeader
export const AlertDialogFooter = DialogFooter

export function AlertDialogTitle({ className, ...props }: ComponentProps<typeof AD.Title>) {
  return <AD.Title className={cn('text-base font-semibold tracking-tight', className)} {...props} />
}

export function AlertDialogDescription({ className, ...props }: ComponentProps<typeof AD.Description>) {
  return <AD.Description className={cn('text-sm leading-relaxed text-muted-foreground', className)} {...props} />
}

export function AlertDialogAction({ className, ...props }: ComponentProps<typeof AD.Action>) {
  return <AD.Action className={cn(buttonVariants(), className)} {...props} />
}

export function AlertDialogCancel({ className, ...props }: ComponentProps<typeof AD.Cancel>) {
  return <AD.Cancel className={cn(buttonVariants({ variant: 'outline' }), className)} {...props} />
}

// ----- Sheet (side panel) ------------------------------------------------------------------------------

export const Sheet = D.Root

export function SheetContent({
  className,
  children,
  side = 'right',
  ...props
}: ComponentProps<typeof D.Content> & { side?: 'left' | 'right' }) {
  return (
    <D.Portal>
      <D.Overlay className={cn(overlayCls, 'bg-black/30')} />
      <D.Content
        className={cn(
          'fixed inset-y-0 z-50 flex h-full w-full max-w-[min(640px,calc(100vw-2rem))] flex-col bg-popover text-popover-foreground shadow-2xl outline-none data-[state=open]:animate-in data-[state=open]:duration-300 data-[state=closed]:animate-out data-[state=closed]:duration-200',
          side === 'right'
            ? 'right-0 border-l data-[state=open]:slide-in-from-right data-[state=closed]:slide-out-to-right'
            : 'left-0 border-r data-[state=open]:slide-in-from-left data-[state=closed]:slide-out-to-left',
          className,
        )}
        {...props}
      >
        {children}
        <D.Close className="absolute top-4 right-4 rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
          <XIcon className="size-4" />
          <span className="sr-only">닫기</span>
        </D.Close>
      </D.Content>
    </D.Portal>
  )
}

export const SheetTitle = DialogTitle
export const SheetDescription = DialogDescription

// ----- Tooltip -----------------------------------------------------------------------------------------

export const TooltipProvider = TT.Provider

export function Tooltip({
  content,
  children,
  side = 'top',
  className,
}: {
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'bottom' | 'left' | 'right'
  className?: string
}) {
  return (
    <TT.Root>
      <TT.Trigger asChild>{children}</TT.Trigger>
      <TT.Portal>
        <TT.Content
          side={side}
          sideOffset={6}
          className={cn(
            'z-50 max-w-72 rounded-md bg-foreground px-2.5 py-1.5 text-xs leading-relaxed text-background shadow-lg data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
            className,
          )}
        >
          {content}
        </TT.Content>
      </TT.Portal>
    </TT.Root>
  )
}

// ----- Popover -----------------------------------------------------------------------------------------

export const Popover = PP.Root
export const PopoverTrigger = PP.Trigger

export function PopoverContent({ className, align = 'start', sideOffset = 6, ...props }: ComponentProps<typeof PP.Content>) {
  return (
    <PP.Portal>
      <PP.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          'z-50 w-72 rounded-lg border bg-popover p-3 text-popover-foreground shadow-xl outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-[0.98] data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
          className,
        )}
        {...props}
      />
    </PP.Portal>
  )
}

// ----- DropdownMenu ------------------------------------------------------------------------------------

export const DropdownMenu = DM.Root
export const DropdownMenuTrigger = DM.Trigger
export const DropdownMenuRadioGroup = DM.RadioGroup

export function DropdownMenuContent({ className, sideOffset = 6, ...props }: ComponentProps<typeof DM.Content>) {
  return (
    <DM.Portal>
      <DM.Content
        sideOffset={sideOffset}
        className={cn(
          'z-50 min-w-40 overflow-hidden rounded-lg border bg-popover p-1 text-popover-foreground shadow-xl data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-[0.98] data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
          className,
        )}
        {...props}
      />
    </DM.Portal>
  )
}

const itemCls =
  "relative flex cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-accent [&_svg:not([class*='size-'])]:size-4 [&_svg]:text-muted-foreground"

export function DropdownMenuItem({ className, ...props }: ComponentProps<typeof DM.Item>) {
  return <DM.Item className={cn(itemCls, className)} {...props} />
}

export function DropdownMenuRadioItem({ className, children, ...props }: ComponentProps<typeof DM.RadioItem>) {
  return (
    <DM.RadioItem className={cn(itemCls, 'pr-8', className)} {...props}>
      {children}
      <DM.ItemIndicator className="absolute right-2 flex size-3.5 items-center justify-center">
        <span className="size-1.5 rounded-full bg-foreground" />
      </DM.ItemIndicator>
    </DM.RadioItem>
  )
}

export function DropdownMenuLabel({ className, ...props }: ComponentProps<typeof DM.Label>) {
  return <DM.Label className={cn('px-2 py-1.5 text-xs font-medium text-muted-foreground', className)} {...props} />
}

export function DropdownMenuSeparator({ className, ...props }: ComponentProps<typeof DM.Separator>) {
  return <DM.Separator className={cn('-mx-1 my-1 h-px bg-border', className)} {...props} />
}
