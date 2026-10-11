from __future__ import annotations

import asyncio
import datetime as dt
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import __version__
from ..context import AppContext
from ..notes.format import parse_note
from ..notes.merge import merge3
from ..people import PersonError
from . import schemas as S
from .auth import require_auth

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_auth)])


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]


def _people(ctx: AppContext, people: str | None) -> list[str]:
    known = ctx.people.ids()
    if not people:
        return known
    wanted = [p.strip() for p in people.split(",") if p.strip()]
    unknown = [p for p in wanted if p not in known]
    if unknown:
        raise HTTPException(404, f"모르는 사람: {', '.join(unknown)}")
    return wanted


def _person(ctx: AppContext, person_id: str) -> str:
    if ctx.people.get(person_id) is None:
        raise HTTPException(404, f"모르는 사람: {person_id}")
    return person_id


def _llm(ctx: AppContext) -> S.LLMStatus:
    return S.LLMStatus(**ctx.extraction.llm_status())


def _person_out(ctx: AppContext, p: dict, stats: dict | None = None) -> dict:
    s = (stats if stats is not None else ctx.people_admin.stats()).get(p["id"], {})
    return {**p, "note_path": ctx.notes.rel_path(p["id"]), "sections": s.get("sections", 0), "items": s.get("items", 0)}


# ---- 조회 ----


@router.get("/meta", response_model=S.MetaOut)
def meta(ctx: Ctx):
    return S.MetaOut(
        version=__version__,
        today=ctx.clock.today(),
        now=ctx.clock.now(),
        timezone=ctx.settings.timezone,
        horizon_days=ctx.settings.horizon_days,
        auth_required=ctx.settings.auth_required,
        llm=_llm(ctx),
    )


# ---- 사람 관리 ----


@router.get("/people", response_model=list[S.PersonOut])
def people(ctx: Ctx):
    stats = ctx.people_admin.stats()
    return [_person_out(ctx, p, stats) for p in ctx.people.list()]


@router.post("/people", response_model=S.PersonOut, status_code=201)
def create_person(ctx: Ctx, body: S.PersonIn):
    try:
        return _person_out(ctx, ctx.people_admin.create(body.name, body.color))
    except PersonError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.patch("/people/{person_id}", response_model=S.PersonSaveOut)
def update_person(ctx: Ctx, person_id: str, body: S.PersonPatch):
    _person(ctx, person_id)
    try:
        out = ctx.people_admin.update(person_id, body.name, body.color)
    except PersonError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"person": _person_out(ctx, out["person"]), "warnings": out["warnings"]}


@router.delete("/people/{person_id}", response_model=S.PersonDeleteOut)
def delete_person(ctx: Ctx, person_id: str):
    _person(ctx, person_id)
    try:
        return ctx.people_admin.delete(person_id)
    except PersonError as exc:
        raise HTTPException(409, str(exc)) from exc


# ---- LLM 상태 ----


@router.get("/llm", response_model=S.LLMStatus)
def llm_status(ctx: Ctx):
    return _llm(ctx)


@router.post("/llm/check", response_model=S.LLMStatus)
def llm_check(ctx: Ctx):
    """지금 바로 노드를 확인한다. 연결되어 있으면 밀린 분석을 이어서 한다."""
    if ctx.extraction.check_health():
        ctx.extraction.retry_waiting()
    return _llm(ctx)


@router.get("/agenda", response_model=S.AgendaOut)
def agenda(ctx: Ctx, people: str | None = None, days: int = Query(14, ge=1, le=90)):
    out = ctx.occurrences.agenda(_people(ctx, people), days)
    review_counts = ctx.reviews.counts()
    for p in out["people"]:
        p["counts"]["reviews"] = review_counts.get(p["person_id"], 0)
    return out


@router.get("/calendar", response_model=S.CalendarOut)
def calendar(
    ctx: Ctx,
    from_: dt.date = Query(alias="from"),
    to: dt.date = Query(),
    people: str | None = None,
):
    if to < from_ or (to - from_).days > 120:
        raise HTTPException(422, "기간은 120일 이내로 주세요")
    return ctx.occurrences.calendar_range(_people(ctx, people), from_, to)


@router.get("/day", response_model=S.DayOut)
def day(ctx: Ctx, date: dt.date, people: str | None = None):
    return ctx.occurrences.day(_people(ctx, people), date)


@router.get("/finance/summary", response_model=S.FinanceOut)
def finance(ctx: Ctx, month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"), people: str | None = None):
    month = month or ctx.clock.today().strftime("%Y-%m")
    return ctx.occurrences.finance(month, _people(ctx, people))


# ---- 회차 조작 ----


@router.post("/occurrences/{occ_id}/complete", response_model=S.ActionOut)
def complete(ctx: Ctx, occ_id: int, body: S.CompleteIn):
    return ctx.actions.complete(occ_id, body.date, body.amount, body.memo)


@router.post("/occurrences/{occ_id}/skip", response_model=S.ActionOut)
def skip(ctx: Ctx, occ_id: int):
    return ctx.actions.skip(occ_id)


@router.post("/occurrences/{occ_id}/snooze", response_model=S.OccurrenceOut)
def snooze(ctx: Ctx, occ_id: int, body: S.SnoozeIn):
    out = ctx.occurrences.snooze(occ_id, body.until)
    ctx.bus.publish("schedule")
    return out


@router.post("/occurrences/{occ_id}/reschedule", response_model=S.OccurrenceOut)
def reschedule(ctx: Ctx, occ_id: int, body: S.RescheduleIn):
    out = ctx.occurrences.reschedule(occ_id, body.date, body.shift_future)
    ctx.bus.publish("schedule")
    return out


# ---- 항목 ----


@router.get("/items/{item_id}", response_model=S.ItemDetailOut)
def item(ctx: Ctx, item_id: int):
    return ctx.items.detail(item_id)


@router.patch("/items/{item_id}", response_model=S.ItemDetailOut)
def patch_item(ctx: Ctx, item_id: int, body: S.ItemPatch):
    return ctx.items.patch(item_id, body.model_dump(exclude_none=True))


# ---- 노트 ----


@router.get("/people/{person_id}/notes", response_model=S.NoteDocOut)
def get_notes(ctx: Ctx, person_id: str):
    _person(ctx, person_id)
    ctx.indexer.ensure_note(person_id)
    text, h = ctx.notes.read(person_id)
    return S.NoteDocOut(person_id=person_id, path=ctx.notes.rel_path(person_id), content=text, hash=h)


@router.put(
    "/people/{person_id}/notes",
    response_model=S.NoteSaveOut,
    responses={409: {"description": "편집기를 연 뒤 노트가 바뀌었고 자동 병합할 수 없음"}},
)
def put_notes(ctx: Ctx, person_id: str, body: S.NotePut):
    _person(ctx, person_id)
    merged = False
    with ctx.notes.lock(person_id):
        current, h = ctx.notes.read(person_id)
        if body.base_hash == h:
            new = body.content
        else:
            base = ctx.notes.recall(body.base_hash)
            if base is None:
                return JSONResponse(
                    status_code=409,
                    content={"code": "stale", "detail": "노트가 다른 곳에서 바뀌었어요. 새로 불러와 주세요.", "current_content": current, "current_hash": h},
                )
            res = merge3(base, body.content, current)
            if res.conflicts:
                return JSONResponse(
                    status_code=409,
                    content={
                        "code": "conflict",
                        "detail": "같은 곳을 다른 곳에서도 고쳤어요: " + ", ".join(res.conflicts),
                        "conflicts": res.conflicts,
                        "current_content": current,
                        "current_hash": h,
                    },
                )
            new, merged = res.text, True
        new_hash = ctx.notes.write(person_id, new, "노트 편집 (앱)") if new != current else h
        saved, _ = ctx.notes.read(person_id)
    ctx.indexer.sync_person(person_id)
    return S.NoteSaveOut(hash=new_hash, merged=merged, content=saved)


@router.post("/people/{person_id}/notes/reparse")
def reparse(ctx: Ctx, person_id: str):
    _person(ctx, person_id)
    return {"queued": ctx.extraction.reparse_person(person_id)}


@router.get("/people/{person_id}/notes/analysis", response_model=S.NoteAnalysisOut)
def analysis(ctx: Ctx, person_id: str):
    _person(ctx, person_id)
    text, _ = ctx.notes.read(person_id)
    return S.NoteAnalysisOut(
        person_id=person_id, memo=parse_note(text).memo, sections=ctx.extraction.cards(person_id), llm=_llm(ctx)
    )


# ---- 확인 필요 ----


@router.get("/reviews", response_model=list[S.ReviewOut])
def reviews(ctx: Ctx, people: str | None = None):
    return ctx.reviews.list(_people(ctx, people))


@router.post("/reviews/{review_id}/resolve", response_model=S.ReviewOut)
def resolve(ctx: Ctx, review_id: int, body: S.ResolveIn):
    return ctx.reviews.resolve(review_id, body.action, body.patch)


# ---- 알림 ----


@router.get("/notifications", response_model=list[S.NotificationOut])
def notifications(ctx: Ctx, people: str | None = None, limit: int = Query(30, ge=1, le=200)):
    return ctx.notifier.recent(_people(ctx, people), limit)


# ---- 서버 푸시 ----


@router.get("/stream")
async def stream(ctx: Ctx, request: Request):
    async def gen():
        with ctx.bus.listen() as queue:
            yield "retry: 3000\n\n"
            yield f"data: {json.dumps({'type': 'hello', 'today': ctx.clock.today().isoformat()})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {msg}\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ---- 운영용 (화면에는 없음) ----


@router.post("/admin/jobs/{name}")
def run_job(ctx: Ctx, name: str):
    jobs = {
        "morning": ctx.notifier.morning_summary,
        "lead": ctx.notifier.lead_alerts,
        "regenerate": ctx.occurrences.regenerate_all,
        "retry-llm": ctx.extraction.retry_waiting,
        "reindex": lambda: ctx.indexer.sync_all(force=True),
    }
    if name not in jobs:
        raise HTTPException(404, f"작업 이름: {', '.join(jobs)}")
    return {"job": name, "result": jobs[name]()}
