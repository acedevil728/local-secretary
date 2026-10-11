"""구성 요소 조립. 테스트는 시계·LLM 클라이언트·데이터 폴더를 바꿔 끼운다."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass

from .core.bus import EventBus
from .core.clock import Clock, make_clock
from .core.config import Settings
from .core.db import Database
from .extraction.apply import ItemApplier
from .extraction.clients import LLMClient, make_client
from .extraction.reviews import ReviewService
from .extraction.service import ExtractionService
from .notes.indexer import NoteIndexer
from .notes.repo import GitRepo, NoteRepository
from .notes.watcher import NoteWatcher
from .notes.writer import NoteWriter
from .notify.channels import build_channels
from .notify.jobs import JobRunner
from .notify.notifier import Notifier
from .occurrences.actions import ActionService
from .occurrences.items import ItemService
from .occurrences.service import OccurrenceService
from .people import PeopleManager, PeopleService
from .scheduling.business_days import BusinessCalendar, KoreanBusinessCalendar

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    settings: Settings
    clock: Clock
    db: Database
    notes: NoteRepository
    calendar: BusinessCalendar
    bus: EventBus
    people: PeopleService
    people_admin: PeopleManager
    occurrences: OccurrenceService
    items: ItemService
    reviews: ReviewService
    indexer: NoteIndexer
    writer: NoteWriter
    extraction: ExtractionService
    actions: ActionService
    notifier: Notifier
    jobs: JobRunner
    watcher: NoteWatcher
    client: LLMClient
    threads: bool = True

    def start(self) -> None:
        self.people.load()
        if self.notes.git:
            self.notes.git.ensure()
        self.indexer.sync_all(force=True)
        self.occurrences.regenerate_all()
        if not self.threads:
            self.extraction.retry_waiting()
            return
        # 시작할 때 LLM 상태를 한 번 확인하고, 연결되어 있을 때만 밀린 분석을 이어서 한다
        self.extraction.check_health()
        self.extraction.retry_waiting()
        self.extraction.start()
        if self.settings.watch_notes:
            self.watcher.start()
        if self.settings.jobs_enabled:
            self.jobs.start()

    def stop(self) -> None:
        self.jobs.stop()
        self.watcher.stop()
        self.extraction.stop()


def prepare_data_dir(settings: Settings) -> None:
    """개발 서버는 예시 데이터(data-sample/)를 복사해서 쓴다. 원본은 건드리지 않는다."""
    d = settings.data_dir
    if (d / "people.json").exists():
        return
    if settings.data_seed and settings.data_seed.exists():
        log.info("예시 데이터 복사: %s → %s", settings.data_seed, d)
        shutil.copytree(settings.data_seed, d, dirs_exist_ok=True)
    d.mkdir(parents=True, exist_ok=True)


def build_context(
    settings: Settings,
    *,
    clock: Clock | None = None,
    client: LLMClient | None = None,
    calendar: BusinessCalendar | None = None,
    threads: bool = True,
) -> AppContext:
    prepare_data_dir(settings)
    clock = clock or make_clock(settings.timezone, settings.clock_fixed)
    db = Database(settings.data_dir / "app.db")
    notes = NoteRepository(settings.data_dir, GitRepo(settings.data_dir, settings.git_enabled) if settings.git_enabled else None)
    calendar = calendar or KoreanBusinessCalendar()
    bus = EventBus()
    people = PeopleService(db, settings.data_dir)
    occurrences = OccurrenceService(db, clock, calendar, settings.horizon_days)
    items = ItemService(db, notes, occurrences, bus)
    applier = ItemApplier(clock)
    reviews = ReviewService(db, clock, bus, applier)
    indexer = NoteIndexer(db, notes, people, clock, occurrences, reviews, bus)
    writer = NoteWriter(notes, indexer)
    people_admin = PeopleManager(people, notes, indexer, db, bus)
    reviews.occurrences = occurrences
    reviews.writer = writer
    client = client or make_client(settings)
    extraction = ExtractionService(db, client, clock, settings, bus, applier, reviews, occurrences)
    indexer.enqueue = extraction.enqueue
    actions = ActionService(db, writer, indexer, occurrences, reviews, clock, bus)
    notifier = Notifier(db, clock, people, occurrences, build_channels(settings, bus))
    jobs = JobRunner(clock, settings, occurrences, notifier, extraction)
    watcher = NoteWatcher(notes, indexer)
    return AppContext(
        settings=settings,
        clock=clock,
        db=db,
        notes=notes,
        calendar=calendar,
        bus=bus,
        people=people,
        people_admin=people_admin,
        occurrences=occurrences,
        items=items,
        reviews=reviews,
        indexer=indexer,
        writer=writer,
        extraction=extraction,
        actions=actions,
        notifier=notifier,
        jobs=jobs,
        watcher=watcher,
        client=client,
        threads=threads,
    )
