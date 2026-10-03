import React, { Component, Suspense } from 'react';
import { useDialogAccessibility } from '../utils/useDialogAccessibility';

function NoticeContent({ label, failed, onClose }) {
  return <>
    <p role={failed ? 'alert' : 'status'}>{failed ? `${label} could not be opened. Your design is still in the editor.` : `Loading ${label}…`}</p>
    <div className="mt-4 flex flex-wrap gap-3">
      {onClose && <button type="button" data-dialog-initial-focus onClick={onClose} className="border border-neutral-500 px-4 py-3">{failed ? 'Close' : 'Cancel'}</button>}
      {failed && <button type="button" onClick={() => window.location.reload()} className="bg-blue-700 px-4 py-3 text-white">Reload app</button>}
    </div>
  </>;
}

function ModalNotice(props) {
  const ref = useDialogAccessibility(props.onClose);
  return <div className="fixed inset-0 z-100 flex items-center justify-center bg-black/60 p-4">
    <div ref={ref} role="dialog" aria-modal="true" aria-label={props.label} tabIndex={-1}
      className="w-full max-w-md rounded-lg border border-neutral-400 bg-white p-6 text-sm shadow-xl dark:bg-neutral-950">
      <NoticeContent {...props} />
    </div>
  </div>;
}

function FeatureNotice(props) {
  return props.inline ? <div className="p-4 text-sm"><NoticeContent {...props} /></div> : <ModalNotice {...props} />;
}

class FeatureBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error) { this.props.onError?.(error); }
  render() {
    return this.state.failed ? <FeatureNotice {...this.props} failed /> : this.props.children;
  }
}

// React.lazy caches a rejected import; a page reload is the reliable retry path.
export default function LazyFeature({ children, ...props }) {
  return <FeatureBoundary {...props}><Suspense fallback={<FeatureNotice {...props} />}>{children}</Suspense></FeatureBoundary>;
}
