import { motion, type HTMLMotionProps } from 'motion/react'

/** Subtle mount transition (opacity + 6px rise). Respects reduced motion via CSS/OS settings. */
export function FadeIn({ delay = 0, ...props }: HTMLMotionProps<'div'> & { delay?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1], delay }}
      {...props}
    />
  )
}
