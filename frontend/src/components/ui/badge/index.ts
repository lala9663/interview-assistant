import { cva, type VariantProps } from 'class-variance-authority'

export { default as Badge } from './Badge.vue'

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

export type BadgeVariants = VariantProps<typeof badgeVariants>
