import { useCallback, useEffect, useRef, useState } from 'react';

export interface UseCopyToClipboardResult {
  /** True for `resetDelayMs` after a successful copy, then flips back to false. */
  copied: boolean;
  /** Copy `text` to the clipboard. Resolves `true` on success, `false` on failure. */
  copy: (text: string) => Promise<boolean>;
}

/**
 * Clipboard-copy state with an auto-resetting "copied" flag.
 *
 * Owns the reset timer so overlapping copies don't stack timeouts, and clears
 * it on unmount to avoid setting state on an unmounted component.
 */
export function useCopyToClipboard(resetDelayMs = 2000): UseCopyToClipboardResult {
  const [copied, setCopied] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearPending = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const copy = useCallback(
    async (text: string): Promise<boolean> => {
      try {
        await navigator.clipboard.writeText(text);
        clearPending();
        setCopied(true);
        timeoutRef.current = setTimeout(() => setCopied(false), resetDelayMs);
        return true;
      } catch {
        // Clipboard API unavailable (e.g. insecure context or denied permission).
        return false;
      }
    },
    [clearPending, resetDelayMs],
  );

  // Clear any pending reset timer when the consumer unmounts.
  useEffect(() => clearPending, [clearPending]);

  return { copied, copy };
}
