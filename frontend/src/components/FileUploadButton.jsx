import React, { useRef } from 'react';

export default function FileUploadButton({ label, accept, multiple = false, disabled = false, onChange, className, children }) {
  const input = useRef(null);
  return <>
    <button type="button" disabled={disabled} aria-label={label} title={label} className={className} onClick={() => { input.current.value = ''; input.current.click(); }}>
      {children || label}
    </button>
    <input ref={input} aria-label={label} type="file" accept={accept} multiple={multiple} hidden onChange={onChange} />
  </>;
}
