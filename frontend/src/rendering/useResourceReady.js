import { createContext, useContext, useLayoutEffect, useState } from 'react';

export const RenderReadinessContext = createContext(null);

export function useResourceReady(ready, error = null) {
  const boundary = useContext(RenderReadinessContext);
  const [token] = useState(() => Symbol('render resource'));
  useLayoutEffect(() => {
    boundary?.set(token, ready, error);
    return () => boundary?.remove(token);
  }, [boundary, token, ready, error]);
}
