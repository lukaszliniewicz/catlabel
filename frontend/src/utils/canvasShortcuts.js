export function ignoreCanvasShortcut(event) {
  if (document.querySelector('[aria-modal="true"]')) return true;
  const target = event.target;
  if (!(target instanceof Element)) return false;
  if (target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="dialog"], [role="treeitem"], [role="tab"], [role="listbox"], [inert]')) return true;
  return (event.code === 'Space' || event.key.startsWith('Arrow')) && Boolean(target.closest('button, a[href], [role="button"]'));
}
