import { Button } from './ui/button';
import { useCopyToClipboard } from '../hooks/useCopyToClipboard';

interface CopyEmailProps {
  email: string;
}

/**
 * Island that copies an email address to the clipboard, swapping its label to
 * "Copied!" for a couple of seconds. Composes the {@link Button} primitive with
 * the {@link useCopyToClipboard} hook; holds no styling or timer logic itself.
 */
export default function CopyEmail({ email }: CopyEmailProps) {
  const { copied, copy } = useCopyToClipboard();

  return (
    <Button variant="ghost" aria-live="polite" onClick={() => void copy(email)}>
      {copied ? 'Copied!' : 'Copy email'}
    </Button>
  );
}
