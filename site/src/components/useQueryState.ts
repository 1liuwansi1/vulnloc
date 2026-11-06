import { useEffect, useState } from 'react';

/** Static-route language navigation preserves explicit interactive state. */
export function useQueryState<T extends string>(name: string, choices: readonly T[], initial: T) {
  const [value, setValue] = useState<T>(initial);
  useEffect(() => {
    const saved = new URLSearchParams(location.search).get(name);
    if (choices.includes(saved as T)) setValue(saved as T);
  }, [name]);
  const choose = (next: T) => {
    setValue(next);
    const params = new URLSearchParams(location.search);
    params.set(name, next);
    history.replaceState(null, '', location.pathname + '?' + params.toString() + location.hash);
  };
  return [value, choose] as const;
}
