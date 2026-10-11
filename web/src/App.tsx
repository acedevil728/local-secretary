import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api/client";
import { subscribe } from "./api/stream";
import type { Meta, Occurrence, Person } from "./api/types";
import { ActionModal } from "./components/ActionModal";
import { DayDrawer } from "./components/DayDrawer";
import { HelpPage } from "./components/HelpPage";
import { ItemDrawer } from "./components/ItemDrawer";
import { OfflineBanner } from "./components/OfflineBanner";
import { Overview } from "./components/Overview";
import { PeoplePage } from "./components/PeoplePage";
import { Personal } from "./components/Personal";
import { TokenGate } from "./components/TokenGate";
import { TopBar } from "./components/TopBar";
import { useConnection, useHashPage, usePersisted, useTheme } from "./lib/hooks";
import { Ctx, type ActionKind, type AppState, type Tab, type View } from "./state";

type Drawer = { kind: "item"; id: number } | { kind: "day"; date: string };
type Modal = { kind: ActionKind; occ: Occurrence; presetDate?: string };

const FALLBACK = ["#3866d1", "#c04c78", "#7a58d0", "#2e7a4c", "#b8661a", "#1f8a99"];
const FALLBACK_DARK = ["#7fa2f2", "#ec8db1", "#ad94ee", "#6cc391", "#e8a15c", "#6fd0dc"];

export default function App() {
  const conn = useConnection();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [bootError, setBootError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [view, setView] = usePersisted<View>("pa.view", "overview", (v) => v === "overview" || v === "person");
  const [pid, setPid] = usePersisted<string>("pa.pid", "");
  const [days, setDays] = usePersisted<number>("pa.n", 14, (v) => [7, 14, 30].includes(v));
  const [tab, setTab] = usePersisted<Tab>("pa.tab", "schedule", (v) => v === "schedule" || v === "note");
  const [themeChoice, theme, cycleTheme] = useTheme();
  const [drawer, setDrawer] = useState<Drawer | null>(null);
  const [modal, setModal] = useState<Modal | null>(null);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [noteJump, setNoteJump] = useState<AppState["noteJump"]>(null);
  const toastTimer = useRef<number>();
  const bumpTimer = useRef<number>();
  const [page, navigate] = useHashPage();

  const toast = useCallback((msg: string) => {
    setToastMsg(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToastMsg(null), 3600);
  }, []);

  const refresh = useCallback(() => {
    // 이벤트가 몰려 와도 한 번만 다시 읽는다
    window.clearTimeout(bumpTimer.current);
    bumpTimer.current = window.setTimeout(() => setVersion((v) => v + 1), 120);
  }, []);

  const load = useCallback(async () => {
    try {
      const [m, p] = await Promise.all([api.get<Meta>("/meta"), api.get<Person[]>("/people")]);
      setMeta(m);
      setPeople(p);
      setBootError(null);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) setBootError("서버에 연결하지 못했어요. 잠시 뒤 다시 시도해요.");
    }
  }, []);

  useEffect(() => {
    if (!conn.needToken) void load();
  }, [load, conn.needToken]);

  useEffect(() => {
    if (conn.needToken) return;
    return subscribe((ev) => {
      if (ev.type === "notification" && ev.title) toast(`${ev.title}\n${ev.body ?? ""}`);
      if (ev.type === "hello" || ev.type === "people") void load();
      refresh();
    });
  }, [conn.needToken, load, refresh, toast]);

  useEffect(() => {
    if (people.length && !people.some((p) => p.id === pid)) setPid(people[0].id);
  }, [people, pid, setPid]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (modal) setModal(null);
      else if (drawer) setDrawer(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modal, drawer]);

  const color = useCallback(
    (id: string) => {
      const i = Math.max(0, people.findIndex((p) => p.id === id));
      const p = people[i];
      if (theme === "dark") return p?.color_dark || FALLBACK_DARK[i % FALLBACK_DARK.length];
      return p?.color || FALLBACK[i % FALLBACK.length];
    },
    [people, theme],
  );

  const state: AppState | null = useMemo(() => {
    if (!meta) return null;
    return {
      meta,
      people,
      today: meta.today,
      days,
      view,
      pid: pid || people[0]?.id || "",
      tab,
      version,
      online: conn.online,
      refresh,
      color,
      name: (id: string) => people.find((p) => p.id === id)?.name ?? id,
      goPerson(id, t) {
        navigate("dashboard");
        setView("person");
        setPid(id);
        if (t) setTab(t);
        setDrawer(null);
      },
      openItem(itemId, owner) {
        navigate("dashboard");
        if (view === "overview" && owner) {
          setView("person");
          setPid(owner);
        }
        setTab("schedule");
        setDrawer({ kind: "item", id: itemId });
      },
      openDay: (iso) => setDrawer({ kind: "day", date: iso }),
      pickedDay: drawer?.kind === "day" ? drawer.date : null,
      act: (kind, occ, presetDate) => setModal({ kind, occ, presetDate }),
      toast,
      gotoNote(id, heading) {
        navigate("dashboard");
        setView("person");
        setPid(id);
        setTab("note");
        setDrawer(null);
        if (heading) setNoteJump({ pid: id, heading, n: Date.now() });
      },
      noteJump,
    };
  }, [meta, people, days, view, pid, tab, version, conn.online, refresh, color, toast, noteJump, drawer, setView, setPid, setTab, navigate]);

  if (conn.needToken) return <TokenGate onDone={() => void load()} />;
  if (!state) {
    return (
      <main>
        <p className="empty">{bootError ?? "불러오는 중…"}</p>
      </main>
    );
  }

  return (
    <Ctx.Provider value={state}>
      <TopBar
        page={page}
        onNavigate={navigate}
        onView={(v) => {
          navigate("dashboard");
          setView(v);
        }}
        onPerson={setPid}
        onDays={setDays}
        themeChoice={themeChoice}
        onTheme={() => {
          cycleTheme();
          const next = ({ light: "다크", dark: "시스템 설정을 따라요", system: "라이트" } as const)[themeChoice];
          toast(`테마: ${next}`);
        }}
      />
      <main>
        {!conn.online && <OfflineBanner lastSync={conn.lastSync} />}
        {page === "help" ? (
          <HelpPage />
        ) : page === "people" ? (
          <PeoplePage
            onChanged={() => {
              void load();
              refresh();
            }}
          />
        ) : state.view === "overview" ? (
          <Overview />
        ) : (
          <Personal onTab={setTab} />
        )}
      </main>
      {drawer?.kind === "item" && <ItemDrawer id={drawer.id} onClose={() => setDrawer(null)} />}
      {drawer?.kind === "day" && <DayDrawer date={drawer.date} onClose={() => setDrawer(null)} />}
      {modal && (
        <ActionModal kind={modal.kind} occ={modal.occ} presetDate={modal.presetDate} onClose={() => setModal(null)} />
      )}
      {toastMsg && (
        <div className="toast" role="status">
          {toastMsg}
        </div>
      )}
    </Ctx.Provider>
  );
}
