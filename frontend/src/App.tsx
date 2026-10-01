import { Header } from "./components/Header";
import { useLocation } from "./lib/router";
import { AlertsPage } from "./pages/AlertsPage";
import { InventoryListPage } from "./pages/InventoryListPage";
import { ItemDetailPage } from "./pages/ItemDetailPage";
import { NewItemPage } from "./pages/NewItemPage";
import { Empty } from "./components/ui";
import { Link } from "./lib/router";

function route(pathname: string) {
  if (pathname === "/") return <InventoryListPage />;
  if (pathname === "/items/new") return <NewItemPage />;
  const detail = pathname.match(/^\/items\/(\d+)$/);
  if (detail) return <ItemDetailPage key={detail[1]} id={Number(detail[1])} />;
  if (pathname === "/alerts") return <AlertsPage />;
  return (
    <Empty title="Page not found">
      <Link to="/">Back to inventory</Link>
    </Empty>
  );
}

export function App() {
  const { pathname } = useLocation();
  return (
    <>
      <Header />
      <main className="container">{route(pathname)}</main>
    </>
  );
}
