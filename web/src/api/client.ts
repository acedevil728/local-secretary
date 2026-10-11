// REST 클라이언트. 기기 토큰은 Authorization 헤더로 보낸다(웹·앱 공통 방식).
// GET 응답은 마지막 것을 보관해 두었다가 연결이 끊기면 그걸 보여 준다.

import { store } from "../lib/storage";

const BASE = "/api/v1";
const TOKEN_KEY = "pa.token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(typeof body === "object" && body && "detail" in body ? String((body as { detail: unknown }).detail) : `HTTP ${status}`);
  }
}

// ---- 연결 상태 (useSyncExternalStore 용) ----

type Conn = { online: boolean; lastSync: string | null; needToken: boolean };
let conn: Conn = { online: true, lastSync: store.get("pa.lastSync"), needToken: false };
const listeners = new Set<() => void>();

function setConn(patch: Partial<Conn>) {
  const next = { ...conn, ...patch };
  if (next.online === conn.online && next.lastSync === conn.lastSync && next.needToken === conn.needToken) return;
  conn = next;
  listeners.forEach((l) => l());
}

export const connection = {
  get: () => conn,
  subscribe(l: () => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },
  markOnline() {
    const now = new Date().toISOString();
    store.set("pa.lastSync", now);
    setConn({ online: true, lastSync: now });
  },
  markOffline: () => setConn({ online: false }),
};

export function getToken(): string | null {
  return store.get(TOKEN_KEY);
}

export function setToken(token: string) {
  store.set(TOKEN_KEY, token.trim());
  setConn({ needToken: false });
}

export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

const memCache = new Map<string, unknown>();
// 기기에 남겨 둘 응답은 대시보드 요약만(노트 원문은 메모리에만). 다시 열었을 때 끊겨 있어도 보이게 한다.
const PERSIST = ["/meta", "/people", "/agenda", "/finance/summary", "/reviews"];
const persistable = (path: string) => PERSIST.some((p) => path === p || path.startsWith(`${p}?`));

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: { ...authHeaders(), ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    connection.markOffline();
    if (method === "GET") {
      const cached = memCache.get(path) ?? (persistable(path) ? store.getJSON(`pa.cache:${path}`) : null);
      if (cached !== undefined && cached !== null) return cached as T;
    }
    throw err;
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (res.status === 401) {
    setConn({ needToken: true });
    throw new ApiError(401, data);
  }
  if (!res.ok) throw new ApiError(res.status, data);
  connection.markOnline();
  if (method === "GET") {
    memCache.set(path, data);
    if (persistable(path)) store.setJSON(`pa.cache:${path}`, data);
  }
  return data as T;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  get: <T>(path: string, params: Record<string, string | number | undefined | null> = {}) =>
    request<T>("GET", path + qs(params)),
  post: <T>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};
