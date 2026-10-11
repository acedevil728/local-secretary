// 백엔드 /api/v1 응답 타입 (app/api/schemas.py 와 같은 모양)

export type Importance = "high" | "normal" | "low";
export type Category = "routine" | "bill" | "loan" | "saving" | "renewal" | "health" | "other";
export type OccStatus = "upcoming" | "due" | "overdue" | "snoozed";

export type Rule =
  | { type: "interval"; every: number; unit: "day" | "week" | "month" | "year"; anchor?: string }
  | { type: "calendar"; rrule: string; adjust: "none" | "next_business_day" }
  | { type: "learned" }
  | { type: "once"; date: string };

export interface Person {
  id: string;
  name: string;
  color: string | null;
  color_dark: string | null;
  note_path?: string | null;
  sections?: number;
  items?: number;
}

export interface PersonSave {
  person: Person;
  warnings: string[];
}

export interface PersonDelete {
  archived_to: string | null;
  warnings: string[];
}

export interface LLMNode {
  url: string | null;
  model: string;
  reachable: boolean;
  has_model: boolean;
  error: string | null;
}

/** available: null = 아직 확인 전(회색), true = 초록, false = 빨강 */
export interface LLMStatus {
  mode: string;
  available: boolean | null;
  endpoint: string | null;
  last_error?: string | null;
  checked_at?: string | null;
  nodes: LLMNode[];
  pending: number;
}

export interface Meta {
  version: string;
  today: string;
  now: string;
  timezone: string;
  horizon_days: number;
  auth_required: boolean;
  llm: LLMStatus;
}

export interface Occurrence {
  id: number;
  item_id: number;
  title: string;
  category: Category;
  importance: Importance;
  amount: number | null;
  assignees: string[];
  owner_id: string;
  raw_date: string;
  due_date: string;
  effective_date: string;
  window_start: string;
  window_end: string;
  window_days: number;
  lead_days: number;
  status: OccStatus;
  days_left: number;
  snoozed_until: string | null;
  moved: boolean;
  priority: number;
  rule_type: string | null;
}

export interface HistoryEvent {
  id: number;
  item_id: number | null;
  title: string;
  heading: string;
  owner_id: string;
  assignees: string[];
  date: string;
  status: "done" | "skipped";
  status_text: string;
  amount: number | null;
  memo: string | null;
  source: "note" | "dashboard";
}

export interface Counts {
  overdue: number;
  today: number;
  week: number;
  total: number;
  reviews: number;
}

export interface Agenda {
  today: string;
  days: number;
  people: { person_id: string; occurrences: Occurrence[]; counts: Counts }[];
}

export interface CalendarData {
  from: string;
  to: string;
  occurrences: Occurrence[];
  events: HistoryEvent[];
  holidays: { date: string; name: string }[];
}

export interface DayData {
  date: string;
  today: string;
  holiday: string | null;
  people: { person_id: string; due: Occurrence[]; near: Occurrence[]; done: HistoryEvent[] }[];
}

export interface FinanceRow {
  date: string;
  item_id: number;
  occurrence_id: number | null;
  title: string;
  amount: number;
  paid: boolean;
  assignees: string[];
}

export interface Finance {
  month: string;
  rows: FinanceRow[];
  total_due: number;
  total_paid: number;
  people: { person_id: string; due: number; paid: number }[];
  previous: { month: string; total_paid: number; total_due: number };
}

export interface ItemDetail {
  id: number;
  title: string;
  heading: string;
  category: Category;
  importance: Importance;
  lead_days: number;
  window_days: number;
  amount: number | null;
  assignees: string[];
  owner_id: string;
  rule: Rule;
  learned_gap_days: number | null;
  source_quote: string | null;
  confidence: number | null;
  user_overrides: Record<string, unknown>;
  next_override: string | null;
  since: string;
  note_path: string;
  note_excerpt: string | null;
  history: HistoryEvent[];
  next: Occurrence[];
}

export interface NoteDoc {
  person_id: string;
  path: string;
  content: string;
  hash: string;
}

export interface NoteSave {
  hash: string;
  merged: boolean;
  content: string | null;
}

export interface Proposal {
  rule: Rule | null;
  title?: string;
  category?: Category;
  importance?: Importance;
  amount?: number | null;
  lead_days?: number;
  window_days?: number;
  events_in_text?: string[];
}

export interface Review {
  id: number;
  person_id: string;
  section_id: number | null;
  section_heading: string | null;
  item_id: number | null;
  kind: "new_item" | "rule_change" | "no_rule" | "invalid" | "cycle_drift" | "write_failed";
  reason: string;
  quote: string | null;
  before: { rule?: Rule | null; amount?: number | null; category?: Category } | null;
  proposed: Proposal | null;
  confidence: number | null;
  state: string;
  created_at: string;
  can_approve: boolean;
}

export type SectionStatus = "pending" | "analyzing" | "waiting_llm" | "done" | "review" | "ignored" | "failed";

export interface SectionCard {
  section_id: number;
  heading: string;
  status: SectionStatus;
  hash: string;
  item: {
    id: number;
    rule: Rule;
    learned_gap_days: number | null;
    category: Category;
    importance: Importance;
    amount: number | null;
    confidence: number | null;
    history_count: number;
    next_date: string | null;
  } | null;
  review: Review | null;
}

export interface NoteAnalysis {
  person_id: string;
  memo: string;
  sections: SectionCard[];
  llm: LLMStatus;
}

export interface StreamEvent {
  type: "hello" | "schedule" | "notes" | "section" | "review" | "notification" | "llm" | "people";
  available?: boolean | null;
  person_id?: string;
  heading?: string;
  status?: string;
  title?: string;
  body?: string;
  today?: string;
}

export interface ConflictBody {
  code: "conflict" | "stale";
  detail: string;
  conflicts?: string[];
  current_content: string;
  current_hash: string;
}
