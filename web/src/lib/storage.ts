// localStorage는 사생활 보호 모드 등에서 막힐 수 있다. 실패해도 화면은 그대로 돈다.
// 여기에는 기기별 편의 설정(보기, 테마, 토큰, 마지막 데이터)만 둔다.

export const store = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key: string, value: string) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* 저장 못 해도 괜찮다 */
    }
  },
  remove(key: string) {
    try {
      localStorage.removeItem(key);
    } catch {
      /* noop */
    }
  },
  getJSON<T>(key: string): T | null {
    const raw = store.get(key);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as T;
    } catch {
      return null;
    }
  },
  setJSON(key: string, value: unknown) {
    try {
      store.set(key, JSON.stringify(value));
    } catch {
      /* noop */
    }
  },
};
