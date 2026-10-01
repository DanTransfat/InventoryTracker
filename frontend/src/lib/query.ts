// A deliberately small data-fetching layer (instead of a library like TanStack Query).
//
// useQuery(key, tags, fetcher) loads data and tracks loading / error / data.
// invalidate(...tags) tells every mounted query with a matching tag to refetch in the
// background. After a mutation we invalidate e.g. ["items", "alerts"], and the header
// badge, the list and the detail page all refresh without a page reload.

import { useCallback, useEffect, useRef, useState } from "react";

type Listener = () => void;
const listeners = new Map<string, Set<Listener>>();

export function invalidate(...tags: string[]): void {
  const fired = new Set<Listener>();
  for (const tag of tags) {
    for (const fn of listeners.get(tag) ?? []) {
      if (!fired.has(fn)) {
        fired.add(fn);
        fn();
      }
    }
  }
}

export interface QueryState<T> {
  data: T | undefined;
  error: Error | undefined;
  /** True only for the first load (no data yet). */
  loading: boolean;
  /** True while any request is in flight, including background refreshes. */
  fetching: boolean;
  refetch: () => void;
}

export function useQuery<T>(key: string, tags: string[], fetcher: (signal: AbortSignal) => Promise<T>): QueryState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [fetching, setFetching] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback(() => {
    controllerRef.current?.abort(); // a newer request always wins over an older one
    const controller = new AbortController();
    controllerRef.current = controller;
    setFetching(true);
    fetcherRef
      .current(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setError(undefined);
      })
      .catch((err: Error) => {
        if (controller.signal.aborted || err.name === "AbortError") return;
        setError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setFetching(false);
      });
  }, []);

  useEffect(() => {
    run();
    return () => controllerRef.current?.abort();
  }, [key, run]);

  const tagKey = tags.join("|");
  useEffect(() => {
    const tagList = tagKey.split("|");
    for (const tag of tagList) {
      if (!listeners.has(tag)) listeners.set(tag, new Set());
      listeners.get(tag)!.add(run);
    }
    return () => {
      for (const tag of tagList) listeners.get(tag)?.delete(run);
    };
  }, [tagKey, run]);

  return { data, error, loading: fetching && data === undefined && !error, fetching, refetch: run };
}
