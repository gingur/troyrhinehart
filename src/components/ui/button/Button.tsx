import { forwardRef } from 'react';
import type { ComponentPropsWithoutRef } from 'react';
import { cx } from '../../../utils/classnames';

export type ButtonVariant = 'primary' | 'ghost';

export interface ButtonProps extends ComponentPropsWithoutRef<'button'> {
  variant?: ButtonVariant;
}

const BASE_CLASSES =
  'inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 disabled:cursor-not-allowed disabled:opacity-50';

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: 'bg-neutral-100 text-neutral-900 hover:bg-white',
  ghost:
    'border border-neutral-700 bg-neutral-900 text-neutral-100 hover:border-neutral-500 hover:bg-neutral-800',
};

/**
 * Presentational button primitive for the design system. Holds no business
 * logic — it styles a native `<button>`, forwards its ref, and passes through
 * every native button prop.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', type = 'button', className, ...props },
  ref,
) {
  const classes = cx(BASE_CLASSES, VARIANT_CLASSES[variant], className);
  return <button ref={ref} type={type} className={classes} {...props} />;
});
