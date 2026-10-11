// 화면 문구. API는 구조화된 값만 주고, 사람이 읽는 말은 여기서 만든다.

import type { Category, Importance, Occurrence, Rule } from "../api/types";
import { md } from "./dates";

export const CAT: Record<Category, string> = {
  routine: "루틴",
  bill: "공과금",
  loan: "대출",
  saving: "저축",
  renewal: "갱신·만기",
  health: "건강",
  other: "기타",
};

export const IMP: Record<Importance, string> = { high: "높음", normal: "보통", low: "낮음" };

const UNIT: Record<string, string> = { day: "일", week: "주", month: "개월", year: "년" };
const BYDAY: Record<string, string> = { MO: "월", TU: "화", WE: "수", TH: "목", FR: "금", SA: "토", SU: "일" };

export function won(v: number | null | undefined): string {
  return v == null ? "" : `${Number(v).toLocaleString("ko-KR")}원`;
}

function rruleText(rrule: string): string {
  const p: Record<string, string> = {};
  for (const part of rrule.split(";")) {
    const [k, v] = part.split("=");
    if (k && v) p[k.toUpperCase()] = v.toUpperCase();
  }
  const interval = Number(p.INTERVAL || 1);
  const dayOfMonth = (v?: string) => {
    if (!v) return "";
    const days = v.split(",");
    if (days.length === 2 && days[1] === "-1" && p.BYSETPOS === "1") return `${days[0]}일(짧은 달은 말일)`;
    return days.map((d) => (d === "-1" ? "말일" : `${d}일`)).join("·");
  };
  switch (p.FREQ) {
    case "DAILY":
      return interval > 1 ? `${interval}일마다` : "매일";
    case "WEEKLY": {
      const days = (p.BYDAY || "").split(",").map((d) => BYDAY[d] ?? d).join("·");
      const head = interval === 2 ? "격주" : interval > 2 ? `${interval}주마다` : "매주";
      return days ? `${head} ${days}요일` : head;
    }
    case "MONTHLY":
      return `${interval > 1 ? `${interval}개월마다` : "매달"} ${dayOfMonth(p.BYMONTHDAY)}`.trim();
    case "YEARLY":
      return `매년 ${p.BYMONTH ? `${p.BYMONTH}월 ` : ""}${dayOfMonth(p.BYMONTHDAY)}`.trim();
    default:
      return rrule;
  }
}

export function ruleText(rule: Rule | null | undefined, learnedGap?: number | null): string {
  if (!rule) return "(규칙 없음)";
  switch (rule.type) {
    case "interval":
      return `${rule.every}${UNIT[rule.unit]}마다 · 마지막 기록 기준`;
    case "learned":
      return learnedGap ? `기록 간격 학습 · 약 ${learnedGap}일마다` : "기록 간격 학습 · 기록 2건 이상 필요";
    case "once":
      return `${md(rule.date)} 1회`;
    case "calendar":
      return rruleText(rule.rrule) + (rule.adjust === "next_business_day" ? " · 휴일이면 다음 영업일" : "");
  }
}

export function ruleCode(rule: Rule | null | undefined): string {
  return rule?.type ?? "-";
}

/** D-3, 오늘, 2일 지남, 미룸 ~10/14 화 */
export function dLabel(o: Occurrence): string {
  if (o.status === "snoozed" && o.snoozed_until) return `미룸 ~${md(o.snoozed_until)}`;
  if (o.status === "overdue") return `${-o.days_left}일 지남`;
  if (o.days_left === 0) return "오늘";
  if (o.days_left < 0) return `${-o.days_left}일 전 · 허용 중`;
  return `D-${o.days_left}`;
}

export function pct(v: number | null | undefined): string {
  return v == null ? "-" : `${Math.round(v * 100)}%`;
}
