import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { connection } from "../api/client";
import { store } from "./storage";

/** 기기에 기억하는 화면 설정(보기, 사람, 기간, 탭). */
export function usePersisted<T extends string | number>(
  key: string,
  initial: T,
  valid: (v: T) => boolean = () => true,
): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    const raw = store.get(key);
    if (raw == null) return initial;
    const parsed = (typeof initial === "number" ? Number(raw) : raw) as T;
    return valid(parsed) ? parsed : initial;
  });
  const set = useCallback(
    (v: T) => {
      setValue(v);
      store.set(key, String(v));
    },
    [key],
  );
  return [value, set];
}

/** 간단한 데이터 읽기. version이 바뀌면(SSE 이벤트) 다시 읽고, 실패하면 마지막 데이터를 유지한다. */
export function useQuery<T>(key: string | null, fetcher: () => Promise<T>, version = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const ref = useRef(fetcher);
  ref.current = fetcher;
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (key == null) return;
    let alive = true;
    ref
      .current()
      .then((d) => {
        if (alive) {
          setData(d);
          setError(null);
        }
      })
      .catch((e: Error) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, [key, version, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data: key == null ? null : data, error, reload };
}

/** 화면 단위 이동: #/ 대시보드, #/help 도움말, #/people 사람 관리 */
export type Page = "dashboard" | "help" | "people";

function readHash(): Page {
  const h = window.location.hash.replace(/^#\/?/, "");
  return h === "help" || h === "people" ? h : "dashboard";
}

export function useHashPage(): [Page, (p: Page) => void] {
  const [page, setPage] = useState<Page>(readHash);
  useEffect(() => {
    const on = () => setPage(readHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const navigate = useCallback((p: Page) => {
    const h = p === "dashboard" ? "#/" : `#/${p}`;
    if (window.location.hash !== h) {
      window.location.hash = h;
      window.scrollTo(0, 0);
    }
    setPage(p);
  }, []);
  return [page, navigate];
}

export function useConnection() {
  return useSyncExternalStore(connection.subscribe, connection.get);
}

// ---- 테마: 라이트 → 다크 → 시스템, 기본은 라이트. 기기마다 따로 기억한다. ----

export type ThemeChoice = "light" | "dark" | "system";

function systemDark(): boolean {
  return typeof matchMedia !== "undefined" && matchMedia("(prefers-color-scheme: dark)").matches;
}

export function useTheme(): [ThemeChoice, "light" | "dark", () => void] {
  const [choice, setChoice] = usePersisted<ThemeChoice>("pa.theme", "light", (v) =>
    ["light", "dark", "system"].includes(v),
  );
  const [sysDark, setSysDark] = useState(systemDark);
  useEffect(() => {
    if (typeof matchMedia === "undefined") return;
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const on = () => setSysDark(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  const resolved = choice === "system" ? (sysDark ? "dark" : "light") : choice;
  useEffect(() => {
    const root = document.documentElement;
    if (choice === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", choice);
  }, [choice]);
  const cycle = useCallback(() => {
    setChoice(({ light: "dark", dark: "system", system: "light" } as const)[choice]);
  }, [choice, setChoice]);
  return [choice, resolved, cycle];
}
