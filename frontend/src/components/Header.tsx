import { api } from "../lib/api";
import { useQuery } from "../lib/query";
import { Link, useLocation } from "../lib/router";

export function Header() {
  const { pathname } = useLocation();
  // Tagged "alerts": any mutation that can change alert state invalidates this tag.
  const summary = useQuery("alert-summary", ["alerts"], (signal) => api.alertSummary(signal));
  const open = summary.data?.open;

  const navClass = (active: boolean) => `nav-link${active ? " active" : ""}`;
  return (
    <header className="app-header">
      <div className="header-inner">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden="true">▤</span> InventoryTracker
        </Link>
        <nav className="nav">
          <Link to="/" className={navClass(pathname === "/" || pathname.startsWith("/items/") && pathname !== "/items/new")}>
            Inventory
          </Link>
          <Link to="/alerts" className={navClass(pathname.startsWith("/alerts"))}>
            Alerts
            <span
              className={`count-badge${open ? " has-alerts" : ""}`}
              aria-label={open === undefined ? "Open alerts loading" : `${open} open alerts`}
              title={summary.error ? "Couldn't load alert count" : undefined}
            >
              {summary.error ? "!" : open ?? "…"}
            </span>
          </Link>
          <Link to="/items/new" className="btn btn-primary btn-sm">
            + New item
          </Link>
        </nav>
      </div>
    </header>
  );
}
