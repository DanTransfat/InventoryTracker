import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// In development the browser calls /api on the Vite server, which forwards to Flask.
// Same-origin requests mean no CORS setup is needed for local work.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", ""); // share the repo-root .env with the backend
  return {
    plugins: [react()],
    envDir: "..",
    server: {
      port: Number(env.FRONTEND_PORT || 5173),
      proxy: {
        "/api": env.VITE_PROXY_TARGET || "http://localhost:8000",
      },
    },
  };
});
