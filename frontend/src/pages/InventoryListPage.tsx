import { useEffect, useState } from "react";
import { api, type Item } from "../lib/api";
import { useQuery } from "../lib/query";
import { Link, useSearchParams } from "../lib/router";
import { Empty, ErrorState, Loading, Pagination, StockBadge } from "../components/ui";

type SortKey = "name" | "sku" | "current_stock";

export function InventoryListPage() {
  // All list state lives in the URL (?q=&low=1&sort=-current_stock&page=2) so it can be bookmarked.
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const low = params.get("low") === "1";
  const sort = params.get("sort") ?? "name";
  const page = Math.max(1, Number(params.get("page")) || 1);

  const [searchText, setSearchText] = useState(q);
  useEffect(() => setSearchText(q), [q]); // back/forward updates the box

  // Debounce typing: update the URL 300 ms after the user stops.
  useEffect(() => {
    if (searchText.trim() === q) return;
    const t = setTimeout(() => setParams({ q: searchText.trim() || null, page: null }, true), 300);
    return () => clearTimeout(t);
  }, [searchText]); // eslint-disable-line react-hooks/exhaustive-deps

  const key = JSON.stringify({ q, low, sort, page });
  const list = useQuery(key, ["items"], (signal) =>
    api.listItems({ search: q, low_stock: low, sort, page, page_size: 20 }, signal),
  );

  const sortBy = (col: SortKey) => {
    const next = sort === col ? `-${col}` : sort === `-${col}` ? col : col;
    setParams({ sort: next === "name" ? null : next, page: null });
  };
  const sortIndicator = (col: SortKey) => (sort === col ? " ▲" : sort === `-${col}` ? " ▼" : "");
  const ariaSort = (col: SortKey) => (sort === col ? "ascending" : sort === `-${col}` ? "descending" : "none");

  return (
    <section>
      <div className="page-head">
        <h1>Inventory</h1>
      </div>

      <div className="toolbar">
        <input
          type="search"
          className="input search"
          placeholder="Search by SKU or name…"
          aria-label="Search by SKU or name"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
        />
        <label className="checkbox">
          <input type="checkbox" checked={low} onChange={(e) => setParams({ low: e.target.checked ? "1" : null, page: null })} />
          Low stock only
        </label>
        {list.fetching && list.data && <span className="muted small">Updating…</span>}
      </div>

      {list.error && !list.data ? (
        <ErrorState error={list.error} onRetry={list.refetch} />
      ) : list.loading || !list.data ? (
        <Loading label="Loading inventory…" />
      ) : list.data.total === 0 ? (
        <Empty title={q || low ? "No items match these filters." : "No items yet."}>
          {q || low ? (
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => { setSearchText(""); setParams({ q: null, low: null, page: null }); }}>
              Clear filters
            </button>
          ) : (
            <Link to="/items/new">Create the first item</Link>
          )}
        </Empty>
      ) : (
        <>
          <div className={`table-wrap${list.fetching ? " is-fetching" : ""}`}>
            <table className="table">
              <thead>
                <tr>
                  <th aria-sort={ariaSort("sku")}>
                    <button type="button" className="th-sort" onClick={() => sortBy("sku")}>SKU{sortIndicator("sku")}</button>
                  </th>
                  <th aria-sort={ariaSort("name")}>
                    <button type="button" className="th-sort" onClick={() => sortBy("name")}>Name{sortIndicator("name")}</button>
                  </th>
                  <th className="num" aria-sort={ariaSort("current_stock")}>
                    <button type="button" className="th-sort" onClick={() => sortBy("current_stock")}>Stock{sortIndicator("current_stock")}</button>
                  </th>
                  <th className="num">Threshold</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {list.data.data.map((item) => (
                  <ItemRow key={item.id} item={item} />
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            page={list.data.page}
            totalPages={list.data.total_pages}
            total={list.data.total}
            noun="item"
            onPage={(p) => setParams({ page: p === 1 ? null : String(p) })}
          />
        </>
      )}
    </section>
  );
}

function ItemRow({ item }: { item: Item }) {
  return (
    <tr className={item.is_low_stock ? "row-low" : undefined}>
      <td className="mono">
        <Link to={`/items/${item.id}`}>{item.sku}</Link>
      </td>
      <td>
        <Link to={`/items/${item.id}`} className="plain-link">{item.name}</Link>
      </td>
      <td className="num strong">
        {item.current_stock} <span className="muted small">{item.unit}</span>
      </td>
      <td className="num">{item.reorder_threshold}</td>
      <td>
        <StockBadge low={item.is_low_stock} />
      </td>
    </tr>
  );
}
