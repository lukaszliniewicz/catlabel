import { useEffect, useRef } from 'react';

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])'
].join(',');

const openDialogs = [];
const coveredElements = new WeakMap();

const coverBackground = (dialog) => {
  const covered = [];
  for (let branch = dialog; branch?.parentElement; branch = branch.parentElement) {
    for (const sibling of branch.parentElement.children) {
      if (sibling === branch) continue;
      const previous = coveredElements.get(sibling) || { count: 0, wasInert: sibling.hasAttribute('inert') };
      previous.count += 1;
      coveredElements.set(sibling, previous);
      sibling.setAttribute('inert', '');
      covered.push(sibling);
    }
  }
  return () => {
    for (const element of covered) {
      const previous = coveredElements.get(element);
      previous.count -= 1;
      if (previous.count === 0) {
        if (!previous.wasInert) element.removeAttribute('inert');
        coveredElements.delete(element);
      }
    }
  };
};

export const useDialogAccessibility = (onClose, { closeOnEscape = true } = {}) => {
  const dialogRef = useRef(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const previouslyFocused = document.activeElement;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const uncoverBackground = coverBackground(dialog);
    const focusTarget = dialog?.querySelector('[autofocus], [data-dialog-initial-focus]')
      || dialog?.querySelector(FOCUSABLE)
      || dialog;
    const initialFocusFrame = requestAnimationFrame(() => {
      if (dialog && !dialog.contains(document.activeElement)) focusTarget?.focus();
    });
    openDialogs.push(dialogRef);

    const handleKeyDown = (event) => {
      if (openDialogs.at(-1) !== dialogRef) return;
      if (event.key === 'Escape' && closeOnEscape && onCloseRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab' || !dialog) return;

      const focusable = [...dialog.querySelectorAll(FOCUSABLE)].filter((element) => (
        element.getClientRects().length > 0 && element.getAttribute('aria-hidden') !== 'true'
      ));
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    const handleFocus = (event) => {
      if (openDialogs.at(-1) === dialogRef && !dialog.contains(event.target)) focusTarget?.focus();
    };
    document.addEventListener('focusin', handleFocus);
    return () => {
      cancelAnimationFrame(initialFocusFrame);
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('focusin', handleFocus);
      const stackIndex = openDialogs.lastIndexOf(dialogRef);
      if (stackIndex >= 0) openDialogs.splice(stackIndex, 1);
      uncoverBackground();
      if (previouslyFocused?.isConnected && !previouslyFocused.closest('[inert]')) previouslyFocused.focus?.();
    };
  }, [closeOnEscape]);

  return dialogRef;
};
