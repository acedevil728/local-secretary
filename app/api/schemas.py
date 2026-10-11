"""API 계약. FastAPI가 여기서 OpenAPI 명세를 만들고, 웹·앱 클라이언트 타입은 그 명세를 따른다."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

Importance = Literal["high", "normal", "low"]
OccStatus = Literal["upcoming", "due", "overdue", "snoozed"]


class PersonOut(BaseModel):
    id: str
    name: str
    color: str | None = None
    color_dark: str | None = None
    note_path: str | None = None
    sections: int = 0
    items: int = 0


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class PersonPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=20)
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class PersonSaveOut(BaseModel):
    person: PersonOut
    warnings: list[str] = []


class PersonDeleteOut(BaseModel):
    archived_to: str | None
    warnings: list[str] = []


class LLMNode(BaseModel):
    url: str | None
    model: str
    reachable: bool
    has_model: bool
    error: str | None = None


class LLMStatus(BaseModel):
    """상단 LLM 불. available: None = 아직 확인 전, True = 초록, False = 빨강."""

    mode: str
    available: bool | None
    endpoint: str | None
    last_error: str | None = None
    checked_at: dt.datetime | None = None
    nodes: list[LLMNode] = []
    pending: int = 0


class MetaOut(BaseModel):
    version: str
    today: dt.date
    now: dt.datetime
    timezone: str
    horizon_days: int
    auth_required: bool
    llm: LLMStatus


class OccurrenceOut(BaseModel):
    id: int
    item_id: int
    title: str
    category: str
    importance: Importance
    amount: int | None
    assignees: list[str]
    owner_id: str
    raw_date: dt.date
    due_date: dt.date
    effective_date: dt.date
    window_start: dt.date
    window_end: dt.date
    window_days: int
    lead_days: int
    status: OccStatus
    days_left: int
    snoozed_until: dt.date | None
    moved: bool
    priority: float
    rule_type: str | None


class EventOut(BaseModel):
    id: int
    item_id: int | None
    title: str
    heading: str
    owner_id: str
    assignees: list[str]
    date: dt.date
    status: Literal["done", "skipped"]
    status_text: str
    amount: int | None
    memo: str | None
    source: Literal["note", "dashboard"]


class Counts(BaseModel):
    overdue: int
    today: int
    week: int
    total: int
    reviews: int = 0


class AgendaPerson(BaseModel):
    person_id: str
    occurrences: list[OccurrenceOut]
    counts: Counts


class AgendaOut(BaseModel):
    today: dt.date
    days: int
    people: list[AgendaPerson]


class HolidayOut(BaseModel):
    date: dt.date
    name: str


class CalendarOut(BaseModel):
    from_: dt.date = Field(alias="from", serialization_alias="from")
    to: dt.date
    occurrences: list[OccurrenceOut]
    events: list[EventOut]
    holidays: list[HolidayOut]

    model_config = {"populate_by_name": True}


class DayPerson(BaseModel):
    person_id: str
    due: list[OccurrenceOut]
    near: list[OccurrenceOut]
    done: list[EventOut]


class DayOut(BaseModel):
    date: dt.date
    today: dt.date
    holiday: str | None
    people: list[DayPerson]


class FinanceRow(BaseModel):
    date: dt.date
    item_id: int
    occurrence_id: int | None
    title: str
    amount: int
    paid: bool
    assignees: list[str]


class FinancePerson(BaseModel):
    person_id: str
    due: int
    paid: int


class FinancePrev(BaseModel):
    month: str
    total_paid: int
    total_due: int


class FinanceOut(BaseModel):
    month: str
    rows: list[FinanceRow]
    total_due: int
    total_paid: int
    people: list[FinancePerson]
    previous: FinancePrev


class ItemDetailOut(BaseModel):
    id: int
    title: str
    heading: str
    category: str
    importance: Importance
    lead_days: int
    window_days: int
    amount: int | None
    assignees: list[str]
    owner_id: str
    rule: dict[str, Any]
    learned_gap_days: int | None
    source_quote: str | None
    confidence: float | None
    prompt_version: str | None
    model: str | None
    user_overrides: dict[str, Any]
    next_override: dt.date | None
    since: dt.date
    note_path: str
    note_excerpt: str | None
    history: list[EventOut]
    next: list[OccurrenceOut]


class ItemPatch(BaseModel):
    importance: Importance | None = None
    lead_days: int | None = Field(None, ge=0, le=60)
    window_days: int | None = Field(None, ge=0, le=60)


class CompleteIn(BaseModel):
    date: dt.date | None = None
    amount: int | None = Field(None, ge=0)
    memo: str | None = Field(None, max_length=200)


class SnoozeIn(BaseModel):
    until: dt.date


class RescheduleIn(BaseModel):
    date: dt.date
    shift_future: bool = False


class ActionOut(BaseModel):
    item_id: int
    line: str
    next: OccurrenceOut | None


class NoteDocOut(BaseModel):
    person_id: str
    path: str
    content: str
    hash: str


class NotePut(BaseModel):
    content: str = Field(max_length=2_000_000)
    base_hash: str


class NoteSaveOut(BaseModel):
    hash: str
    merged: bool
    content: str | None = None


class ReviewOut(BaseModel):
    id: int
    person_id: str
    section_id: int | None
    section_heading: str | None
    item_id: int | None
    kind: str
    reason: str
    quote: str | None
    before: dict[str, Any] | None
    proposed: dict[str, Any] | None
    confidence: float | None
    state: str
    created_at: dt.datetime
    can_approve: bool


class ResolveIn(BaseModel):
    action: Literal["approve", "edit", "dismiss"]
    patch: dict[str, Any] | None = None


class CardItem(BaseModel):
    id: int
    rule: dict[str, Any]
    learned_gap_days: int | None
    category: str
    importance: Importance
    amount: int | None
    confidence: float | None
    history_count: int
    next_date: dt.date | None


class SectionCard(BaseModel):
    section_id: int
    heading: str
    status: str
    hash: str
    item: CardItem | None
    review: ReviewOut | None


class NoteAnalysisOut(BaseModel):
    person_id: str
    memo: str
    sections: list[SectionCard]
    llm: LLMStatus


class NotificationOut(BaseModel):
    key: str
    person_id: str
    kind: str
    title: str | None
    body: str | None
    sent_at: dt.datetime
