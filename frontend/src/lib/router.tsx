// Minimal client-side router built on the History API.
// The URL is the single source of truth for which page and which list filters are shown.

import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from "react";

const EVENT = "app:navigate";

export function navigate(to: string, opts: { replace?: boolean } = {}): void {
  if (opts.replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  window.dispatchEvent(new Event(EVENT));
}

export function useLocation(): { pathname: string; search: string } {
  const read = () => ({ pathname: window.location.pathname, search: window.location.search });
  const [loc, setLoc] = useState(read);
  useEffect(() => {
    const update = () => setLoc(read());
    window.addEventListener("popstate", update);
    window.addEventListener(EVENT, update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener(EVENT, update);
    };
  }, []);
  return loc;
}

/** Read and update query-string parameters for the current page. */
export function useSearchParams(): [URLSearchParams, (updates: Record<string, string | null>, replace?: boolean) => void] {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  const update = (updates: Record<string, string | null>, replace = false) => {
    const next = new URLSearchParams(window.location.search);
    for (const [k, v] of Object.entries(updates)) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, v);
    }
    const s = next.toString();
    navigate(`${window.location.pathname}${s ? `?${s}` : ""}`, { replace });
  };
  return [params, update];
}

export function Link({ to, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) {
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    // Let the browser handle new-tab / new-window clicks.
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(to);
    window.scrollTo(0, 0);
  };
  return <a href={to} onClick={handle} {...rest} />;
}
