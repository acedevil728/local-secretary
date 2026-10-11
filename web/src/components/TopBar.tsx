import type { Page, ThemeChoice } from "../lib/hooks";
import { useApp, type View } from "../state";
import { LlmLight } from "./LlmLight";

interface Props {
  page: Page;
  onNavigate(p: Page): void;
  onView(v: View): void;
  onPerson(pid: string): void;
  onDays(n: number): void;
  onTheme(): void;
  themeChoice: ThemeChoice;
}

const THEME_LABEL: Record<ThemeChoice, string> = { light: "라이트", dark: "다크", system: "시스템" };

export function TopBar({ page, onNavigate, onView, onPerson, onDays, onTheme, themeChoice }: Props) {
  const app = useApp();
  const onDash = page === "dashboard";
  return (
    <header className="bar">
      <div className="bar-in">
        <button className="brand" onClick={() => onNavigate("dashboard")}>
          개인 비서 대시보드
        </button>
        <div className="seg" role="group" aria-label="보기 전환">
          <button aria-pressed={onDash && app.view === "overview"} onClick={() => onView("overview")}>
            전체 보기
          </button>
          <button aria-pressed={onDash && app.view === "person"} onClick={() => onView("person")}>
            개인 보기
          </button>
        </div>
        <label className="ctl" hidden={!onDash || app.view !== "person"}>
          사람
          <select value={app.pid} onChange={(e) => onPerson(e.target.value)}>
            {app.people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <div className="ctl" hidden={!onDash}>
          다음
          <div className="seg" role="group" aria-label="기간">
            {[7, 14, 30].map((n) => (
              <button key={n} aria-pressed={app.days === n} onClick={() => onDays(n)}>
                {n}일
              </button>
            ))}
          </div>
        </div>
        <div className="bar-tools">
          <LlmLight />
          <button className="tool-btn" aria-pressed={page === "people"} onClick={() => onNavigate("people")}>
            사람 관리
          </button>
          <button className="tool-btn" aria-pressed={page === "help"} onClick={() => onNavigate("help")}>
            도움말
          </button>
          <button className="theme-btn" onClick={onTheme} title="라이트 → 다크 → 시스템 순으로 바뀌어요">
            <i />
            <span>테마: {THEME_LABEL[themeChoice]}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
