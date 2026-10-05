import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiUrl = new URL(env.VITE_API_BASE_URL || "http://localhost:8000");
  const apiOrigin = apiUrl.origin;
  const websocketOrigin = `${apiUrl.protocol === "https:" ? "wss:" : "ws:"}//${apiUrl.host}`;
  const devSocket = mode === "development" ? " ws://localhost:5173" : "";
  const devInline = mode === "development" ? " 'unsafe-inline'" : "";
  const csp = [
    "default-src 'self'",
    `script-src 'self'${devInline}`,
    `style-src 'self'${devInline}`,
    "img-src 'self' data:",
    `connect-src 'self' ${apiOrigin} ${websocketOrigin}${devSocket}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");

  return {
    base: env.VITE_BASE_PATH || "/",
    plugins: [
      react(),
      {
        name: "plight-content-security-policy",
        transformIndexHtml(html) {
          return html.replace(
            "<!-- PLIGHT_CSP -->",
            `<meta http-equiv="Content-Security-Policy" content="${csp}">`,
          );
        },
      },
    ],
  };
});
