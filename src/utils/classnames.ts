export type ClassValue = string | false | null | undefined;

/** Join truthy class names into a single space-separated string. */
export function cx(...classes: ClassValue[]): string {
  return classes.filter(Boolean).join(' ');
}
