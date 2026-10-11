// 날짜는 API와 같은 ISO 문자열(YYYY-MM-DD)로 다룬다. 시간대 영향이 없게 UTC로 계산한다.

export const WD = "일월화수목금토";

export function toDays(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d) / 864e5;
}

export function fromDays(n: number): string {
  return new Date(n * 864e5).toISOString().slice(0, 10);
}

export function parts(iso: string) {
  const x = new Date(toDays(iso) * 864e5);
  return { y: x.getUTCFullYear(), m: x.getUTCMonth(), d: x.getUTCDate(), w: x.getUTCDay() };
}

export const addDays = (iso: string, n: number) => fromDays(toDays(iso) + n);
export const diffDays = (a: string, b: string) => toDays(a) - toDays(b);

export function ymd(y: number, m: number, d: number): string {
  return fromDays(Date.UTC(y, m, d) / 864e5);
}

export function lastDay(y: number, m: number): number {
  return new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
}

/** 10/14 화 */
export function md(iso: string): string {
  const p = parts(iso);
  return `${p.m + 1}/${p.d} ${WD[p.w]}`;
}

export function longDate(iso: string): string {
  const p = parts(iso);
  return `${p.y}년 ${p.m + 1}월 ${p.d}일 (${WD[p.w]})`;
}

/** 일요일 시작 월간 달력 칸들 */
export function monthGrid(y: number, m: number): string[] {
  const first = ymd(y, m, 1);
  const start = toDays(first) - parts(first).w;
  const last = ymd(y, m, lastDay(y, m));
  const end = toDays(last) + (6 - parts(last).w);
  const out: string[] = [];
  for (let d = start; d <= end; d++) out.push(fromDays(d));
  return out;
}

export function monthKey(iso: string): string {
  return iso.slice(0, 7);
}
