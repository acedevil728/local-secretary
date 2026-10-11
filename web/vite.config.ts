/// <reference types="node" />
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// 주소·포트는 프로젝트 루트의 .env.local(+ 환경 변수)에서 읽는다. 백엔드(app/core/config.py)와 같은 키:
//   WEB_HOST, WEB_PORT = 이 개발 서버 / HOST, PORT = /api 를 넘길 백엔드
// 기본은 이 PC에서만 열린다. 태블릿에서 보려면 start 스크립트의 -Lan / --lan (= vite --host).
// 개발 설정은 인증이 꺼져 있으므로 믿을 수 있는 네트워크(Tailscale)에서만 연다.
const PROJECT_ROOT = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig(({ mode }) => {
  // 세 번째 인자 "" = 접두어 없이 모든 키. 설정 파일 안에서만 쓰고 화면 코드로는 넘기지 않는다
  // (화면에 노출되는 건 VITE_ 로 시작하는 키뿐이고, 그런 키는 쓰지 않는다).
  const env = loadEnv(mode, PROJECT_ROOT, "");
  const apiHost = !env.HOST || env.HOST === "0.0.0.0" || env.HOST === "::" ? "127.0.0.1" : env.HOST;
  const apiPort = env.PORT || "8000";
  return {
    plugins: [react()],
    server: {
      host: env.WEB_HOST || "127.0.0.1",
      port: Number(env.WEB_PORT || 5173),
      strictPort: true,
      proxy: { "/api": { target: `http://${apiHost}:${apiPort}`, changeOrigin: false } },
    },
    build: { outDir: "dist", sourcemap: false },
  };
});
