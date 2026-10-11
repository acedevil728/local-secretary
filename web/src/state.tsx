import { createContext, useContext } from "react";
import type { Meta, Occurrence, Person } from "./api/types";

export type View = "overview" | "person";
export type Tab = "schedule" | "note";
export type ActionKind = "complete" | "snooze" | "move" | "skip";

export interface AppState {
  meta: Meta;
  people: Person[];
  today: string;
  days: number;
  view: View;
  pid: string;
  tab: Tab;
  /** SSE 이벤트가 오면 올라간다. 화면은 이 값이 바뀌면 다시 읽는다. */
  version: number;
  online: boolean;
  refresh(): void;
  color(pid: string): string;
  name(pid: string): string;
  goPerson(pid: string, tab?: Tab): void;
  openItem(itemId: number, pid?: string): void;
  openDay(iso: string): void;
  pickedDay: string | null;
  act(kind: ActionKind, o: Occurrence, presetDate?: string): void;
  toast(msg: string): void;
  gotoNote(pid: string, heading?: string): void;
  noteJump: { pid: string; heading: string; n: number } | null;
}

export const Ctx = createContext<AppState | null>(null);

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("AppState 없음");
  return v;
}

/** 사람 색을 CSS 변수로 넘긴다. */
export function pcStyle(color: string): React.CSSProperties {
  return { ["--pc" as string]: color } as React.CSSProperties;
}
