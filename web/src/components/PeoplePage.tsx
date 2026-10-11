import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Person, PersonDelete, PersonSave } from "../api/types";
import { pcStyle, useApp } from "../state";

const NAME_RULE = /^[^\s·,、/()（）:：]{1,20}$/;

/** 사람 관리: 추가 · 이름/색 바꾸기 · 삭제(노트는 _archive로 옮겨 남긴다) */
export function PeoplePage({ onChanged }: { onChanged(): void }) {
  const app = useApp();
  const [name, setName] = useState("");
  const [color, setColor] = useState("");
  const [busy, setBusy] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [confirm, setConfirm] = useState<Person | null>(null);

  const fail = (e: unknown) => app.toast(e instanceof ApiError || e instanceof Error ? e.message : "처리하지 못했어요");

  const add = async () => {
    if (!NAME_RULE.test(name.trim())) {
      app.toast("이름은 1~20자, 공백과 · , / ( ) : 없이 적어 주세요");
      return;
    }
    setBusy(true);
    try {
      const p = await api.post<Person>("/people", { name: name.trim(), color: color || null });
      app.toast(`${p.name}을(를) 추가했어요 · 노트 ${p.note_path}`);
      setName("");
      setColor("");
      onChanged();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const save = async (p: Person, patch: { name?: string; color?: string }) => {
    try {
      const r = await api.patch<PersonSave>(`/people/${p.id}`, patch);
      setWarnings(r.warnings);
      app.toast(`${r.person.name} 정보를 바꿨어요`);
      onChanged();
    } catch (e) {
      fail(e);
    }
  };

  const remove = async (p: Person) => {
    setBusy(true);
    try {
      const r = await api.del<PersonDelete>(`/people/${p.id}`);
      setWarnings(r.warnings);
      app.toast(`${p.name}을(를) 지웠어요${r.archived_to ? ` · 노트는 ${r.archived_to}에 남겼어요` : ""}`);
      setConfirm(null);
      onChanged();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <section className="phead">
        <h1>사람 관리</h1>
        <span className="req">F1</span>
      </section>
      {warnings.length > 0 && (
        <div className="banner off">
          <div style={{ display: "grid", gap: 4 }}>
            {warnings.map((w, i) => (
              <span key={i}>{w}</span>
            ))}
          </div>
          <button className="btn sm" onClick={() => setWarnings([])}>
            확인
          </button>
        </div>
      )}
      <section className="panel">
        <div className="sec-h">
          <h2>사람 추가</h2>
        </div>
        <form
          className="add-person"
          onSubmit={(e) => {
            e.preventDefault();
            void add();
          }}
        >
          <label>
            이름
            <input value={name} maxLength={20} placeholder="예: 하린" onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            색 (선택)
            <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="color" value={color || "#3866d1"} onChange={(e) => setColor(e.target.value)} aria-label="색 고르기" />
              <span className="muted" style={{ fontSize: 12 }}>
                {color ? color : "안 고르면 겹치지 않는 색을 줘요"}
              </span>
            </span>
          </label>
          <button className="btn pri" type="submit" disabled={busy || !app.online || !name.trim()}>
            추가
          </button>
        </form>
        <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>
          추가하면 <code>people/&lt;id&gt;/notes.md</code> 노트가 만들어져요. 이름은 공동 담당 줄 <code>(공동: 이름)</code>에 그대로 쓰이므로
          공백과 · , / ( ) : 는 쓸 수 없어요.
        </p>
      </section>
      <section className="panel">
        <div className="sec-h">
          <h2>등록된 사람</h2>
          <span className="sp muted" style={{ fontSize: 12 }}>
            {app.people.length}명
          </span>
        </div>
        <ul className="list">
          {app.people.map((p) => (
            <PersonRow
              key={p.id}
              p={p}
              color={app.color(p.id)}
              canDelete={app.people.length > 1}
              onSave={(patch) => save(p, patch)}
              onDelete={() => setConfirm(p)}
            />
          ))}
        </ul>
      </section>
      {confirm && (
        <>
          <button className="mscrim" aria-label="닫기" onClick={() => setConfirm(null)} />
          <div className="modal" role="dialog" aria-modal="true">
            <h3>{confirm.name}을(를) 지울까요?</h3>
            <p style={{ margin: 0, fontSize: 13 }}>
              노트는 지우지 않고 <code>people/_archive/</code>로 옮겨 남겨요. 이 사람의 일정과 확인 필요 항목은 대시보드에서 사라지고,
              다른 노트의 <code>(공동: {confirm.name})</code> 줄은 공동 담당에서 빠져요.
            </p>
            <div className="row-b">
              <button className="btn" onClick={() => setConfirm(null)}>
                취소
              </button>
              <button className="btn danger" disabled={busy} onClick={() => remove(confirm)}>
                삭제
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function PersonRow(props: {
  p: Person;
  color: string;
  canDelete: boolean;
  onSave(patch: { name?: string; color?: string }): void;
  onDelete(): void;
}) {
  const app = useApp();
  const { p } = props;
  const [name, setName] = useState(p.name);
  const [color, setColor] = useState(p.color ?? "#3866d1");
  useEffect(() => setName(p.name), [p.name]);
  useEffect(() => setColor(p.color ?? "#3866d1"), [p.color]);
  const nameChanged = name.trim() !== p.name;
  const colorChanged = color.toLowerCase() !== (p.color ?? "#3866d1").toLowerCase();
  return (
    <li className="prow" style={pcStyle(props.color)}>
      <input type="color" value={color} aria-label={`${p.name} 색 바꾸기`} disabled={!app.online} onChange={(e) => setColor(e.target.value)} />
      <div className="pmain">
        <input className="pname-in" value={name} maxLength={20} aria-label="이름" onChange={(e) => setName(e.target.value)} />
        <span className="muted" style={{ fontSize: 12 }}>
          {p.note_path} · 섹션 {p.sections ?? 0} · 추적 항목 {p.items ?? 0}
        </span>
      </div>
      <div className="acts">
        {(nameChanged || colorChanged) && (
          <button
            className="btn pri"
            disabled={!app.online || !NAME_RULE.test(name.trim())}
            onClick={() => props.onSave({ ...(nameChanged ? { name: name.trim() } : {}), ...(colorChanged ? { color } : {}) })}
          >
            저장
          </button>
        )}
        <button className="btn" onClick={() => app.goPerson(p.id, "schedule")}>
          일정
        </button>
        <button className="btn" onClick={() => app.gotoNote(p.id)}>
          노트
        </button>
        <button className="btn" disabled={!props.canDelete || !app.online} onClick={props.onDelete} title={props.canDelete ? undefined : "마지막 한 사람은 지울 수 없어요"}>
          삭제
        </button>
      </div>
    </li>
  );
}
