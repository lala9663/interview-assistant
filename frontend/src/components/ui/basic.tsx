/** Small presentational primitives: Card, Badge, Input, Textarea, Label, Skeleton, Kbd, Separator. */
import { cva, type VariantProps } from 'class-variance-authority'
import { Label as LabelPrimitive, Separator as SeparatorPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

export function Card({ className, ...props }: ComponentProps<'div'>) {
  return <div data-slot="card" className={cn('rounded-xl border bg-card text-card-foreground shadow-soft', className)} {...props} />
}

export function CardHeader({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('flex items-start justify-between gap-3 px-5 pt-4 pb-3', className)} {...props} />
}

export function CardTitle({ className, ...props }: ComponentProps<'h3'>) {
  return <h3 className={cn('text-[15px] leading-6 font-semibold tracking-tight', className)} {...props} />
}

export function CardDescription({ className, ...props }: ComponentProps<'p'>) {
  return <p className={cn('text-[13px] text-muted-foreground', className)} {...props} />
}

export function CardContent({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('px-5 pb-5', className)} {...props} />
}

export const badgeVariants = cva(
  'inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap [&_svg]:size-3',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        outline: 'border-border text-muted-foreground',
        brand: 'border-brand-border bg-brand-soft text-brand',
        success: 'border-transparent bg-[color-mix(in_oklch,var(--success)_13%,transparent)] text-success',
        warning: 'border-transparent bg-[color-mix(in_oklch,var(--warning)_15%,transparent)] text-warning',
        danger: 'border-transparent bg-[color-mix(in_oklch,var(--danger)_13%,transparent)] text-danger',
        live: 'border-transparent bg-[color-mix(in_oklch,var(--live)_14%,transparent)] text-live',
      },
    },
    defaultVariants: { variant: 'secondary' },
  },
)

export function Badge({ className, variant, ...props }: ComponentProps<'span'> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
}

export function Input({ className, type, ...props }: ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        'flex h-9 w-full min-w-0 rounded-md border border-input bg-card px-3 py-1 text-sm transition-[border-color,box-shadow] outline-none placeholder:text-muted-foreground/80 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive',
        className,
      )}
      {...props}
    />
  )
}

export function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        'flex min-h-16 w-full rounded-md border border-input bg-card px-3 py-2 text-sm leading-relaxed transition-[border-color,box-shadow] outline-none placeholder:text-muted-foreground/80 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}

export function Label({ className, ...props }: ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      data-slot="label"
      className={cn('text-[13px] leading-none font-medium select-none peer-disabled:opacity-50', className)}
      {...props}
    />
  )
}

export function Separator({ className, orientation = 'horizontal', ...props }: ComponentProps<typeof SeparatorPrimitive.Root>) {
  return (
    <SeparatorPrimitive.Root
      decorative
      orientation={orientation}
      className={cn('shrink-0 bg-border', orientation === 'horizontal' ? 'h-px w-full' : 'h-full w-px', className)}
      {...props}
    />
  )
}

export function Skeleton({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden
      className={cn(
        'animate-shimmer rounded-md bg-[linear-gradient(90deg,var(--muted)_0%,color-mix(in_oklch,var(--muted)_55%,var(--card))_50%,var(--muted)_100%)] bg-[length:200%_100%]',
        className,
      )}
      {...props}
    />
  )
}

export function Kbd({ className, ...props }: ComponentProps<'kbd'>) {
  return (
    <kbd
      className={cn(
        'pointer-events-none inline-flex h-5 min-w-5 items-center justify-center gap-0.5 rounded border bg-muted px-1 font-sans text-[11px] font-medium text-muted-foreground',
        className,
      )}
      {...props}
    />
  )
}
