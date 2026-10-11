"""HTTP API 통합 테스트. 머리 자르기 시나리오를 처음부터 끝까지 돌린다(Phase 1 완료 기준)."""

from app.api.auth import TokenStore
from tests.conftest import KIM

HAIR = "## 머리 자르기\n나는 5주에 1번 머리를 잘라. 2026년 10월 10일에 머리를 잘랐음\n<!-- history -->\n"


def _note(client, pid):
    r = client.get(f"/api/v1/people/{pid}/notes")
    assert r.status_code == 200
    return r.json()


def _save(client, pid, content, base_hash):
    return client.put(f"/api/v1/people/{pid}/notes", json={"content": content, "base_hash": base_hash})


def _agenda(client, pid, days=14):
    r = client.get("/api/v1/agenda", params={"people": pid, "days": days})
    assert r.status_code == 200
    return r.json()["people"][0]["occurrences"]


def test_hair_scenario_end_to_end(api):
    ctx, client = api(people=KIM)
    doc = _note(client, "kim")
    r = _save(client, "kim", doc["content"] + "\n" + HAIR, doc["hash"])
    assert r.status_code == 200
    ctx.extraction.run_pending()

    # 문장 속 날짜가 이력 줄로 옮겨졌고, 원문 문장은 그대로다
    text = _note(client, "kim")["content"]
    assert "2026년 10월 10일에 머리를 잘랐음\n<!-- history -->\n- 2026-10-10 완료\n" in text

    occ = _agenda(client, "kim", 60)
    assert [(o["title"], o["due_date"], o["window_start"], o["window_end"]) for o in occ] == [
        ("머리 자르기", "2026-11-14", "2026-11-11", "2026-11-17")
    ]

    # 11/13: 알림 구간에 들어와 있고, 완료를 누르면 노트에 이력 줄이 붙는다
    ctx.clock.set("2026-11-13T09:00")  # 테스트 시계만 옮긴다(화면에는 날짜를 바꾸는 기능이 없다)
    ctx.occurrences.regenerate_all()
    occ = _agenda(client, "kim")
    assert occ[0]["status"] == "due" and occ[0]["days_left"] == 1
    r = client.post(f"/api/v1/occurrences/{occ[0]['id']}/complete", json={})
    assert r.status_code == 200, r.text
    assert r.json()["line"] == "- 2026-11-13 완료 (대시보드)"
    assert r.json()["next"]["due_date"] == "2026-12-18"

    text = _note(client, "kim")["content"]
    assert "- 2026-10-10 완료\n- 2026-11-13 완료 (대시보드)\n" in text
    detail = client.get(f"/api/v1/items/{occ[0]['item_id']}").json()
    assert [h["date"] for h in detail["history"]] == ["2026-11-13", "2026-10-10"]
    assert detail["source_quote"].startswith("나는 5주에 1번")


def test_sample_overview_endpoints(api):
    ctx, client = api()
    meta = client.get("/api/v1/meta").json()
    assert meta["today"] == "2026-10-10" and "clock_adjustable" not in meta
    assert client.put("/api/v1/admin/clock", json={"date": "2026-11-13"}).status_code in (404, 405)

    people = client.get("/api/v1/agenda", params={"days": 14}).json()["people"]
    by = {p["person_id"]: p for p in people}
    assert by["p1"]["counts"]["overdue"] == 1  # 엔진오일 (9/28 + 7일 허용 지남)
    assert by["p2"]["counts"]["today"] == 1  # 적금 10/10
    assert by["p2"]["counts"]["reviews"] == 1 and by["p3"]["counts"]["reviews"] == 1  # 요가, 보일러

    cal = client.get("/api/v1/calendar", params={"from": "2026-09-27", "to": "2026-11-07"}).json()
    titles = {(o["title"], o["effective_date"]) for o in cal["occurrences"]}
    assert ("아파트 관리비", "2026-10-26") in titles  # 10/25 일요일 → 다음 영업일
    assert ("도시가스 요금", "2026-11-02") in titles  # 10/31 토요일 → 11/2
    assert {"date": "2026-10-09", "name": "한글날"} in cal["holidays"]
    assert any(e["title"] == "머리 자르기" and e["date"] == "2026-10-10" for e in cal["events"])

    day = client.get("/api/v1/day", params={"date": "2026-11-12", "people": "p1"}).json()
    assert [o["title"] for o in day["people"][0]["near"]] == ["머리 자르기"]  # 11/14 ± 3일 구간 안

    fin = client.get("/api/v1/finance/summary", params={"month": "2026-10"}).json()
    rows = {(r["title"], r["paid"]) for r in fin["rows"]}
    assert ("아파트 관리비", False) in rows and ("적금 납입", False) in rows
    shared = next(p for p in fin["people"] if p["person_id"] == "p2")
    assert shared["due"] >= 230000  # 공동 항목은 담당자 모두에게 잡힌다


def test_note_save_merges_dashboard_history(api):
    ctx, client = api()
    opened = _note(client, "p1")
    # 편집기를 연 사이에 대시보드에서 완료
    occ = next(o for o in _agenda(client, "p1") if o["title"] == "전세자금대출 이자")
    assert client.post(f"/api/v1/occurrences/{occ['id']}/complete", json={"amount": 412000}).status_code == 200
    edited = opened["content"].replace("보통 23만원 안팎", "보통 24만원 안팎")
    r = _save(client, "p1", edited, opened["hash"])
    assert r.status_code == 200 and r.json()["merged"] is True
    text = _note(client, "p1")["content"]
    assert "보통 24만원 안팎" in text and "- 2026-10-10 완료 412,000원 (대시보드)" in text


def test_note_conflict_returns_409(api):
    ctx, client = api()
    opened = _note(client, "p1")
    other = opened["content"].replace("5주에 1번", "6주에 1번")
    assert _save(client, "p1", other, opened["hash"]).status_code == 200
    mine = opened["content"].replace("5주에 1번", "4주에 1번")
    r = _save(client, "p1", mine, opened["hash"])
    assert r.status_code == 409 and r.json()["code"] == "conflict"
    assert "6주에 1번" in r.json()["current_content"]


def test_snooze_reschedule_skip(api):
    ctx, client = api()
    occ = {}
    for o in sorted(_agenda(client, "p2", 30), key=lambda o: o["due_date"]):
        occ.setdefault(o["title"], o)  # 항목마다 가장 가까운 회차
    r = client.post(f"/api/v1/occurrences/{occ['적금 납입']['id']}/snooze", json={"until": "2026-10-13"})
    assert r.json()["status"] == "snoozed"

    lens = occ["콘택트렌즈 교체"]
    r = client.post(f"/api/v1/occurrences/{lens['id']}/reschedule", json={"date": "2026-10-17", "shift_future": False})
    assert r.json()["effective_date"] == "2026-10-17" and r.json()["moved"] is True
    r = client.post(f"/api/v1/occurrences/{lens['id']}/reschedule", json={"date": "2026-10-18", "shift_future": True})
    assert r.json()["due_date"] == "2026-10-18"
    assert [o["due_date"] for o in _agenda(client, "p2", 30) if o["title"] == "콘택트렌즈 교체"][:2] == ["2026-10-18", "2026-11-01"]

    nail = occ["네일 관리"]
    r = client.post(f"/api/v1/occurrences/{nail['id']}/skip")
    assert r.json()["line"] == "- 2026-10-17 건너뜀 (대시보드)"
    assert r.json()["next"]["due_date"] == "2026-11-07"


def test_importance_patch_survives_reanalysis(api):
    ctx, client = api()
    occ = next(o for o in _agenda(client, "p1", 60) if o["title"] == "머리 자르기")
    r = client.patch(f"/api/v1/items/{occ['item_id']}", json={"importance": "high"})
    assert r.json()["importance"] == "high"
    client.post("/api/v1/people/p1/notes/reparse")
    ctx.extraction.run_pending()
    assert client.get(f"/api/v1/items/{occ['item_id']}").json()["importance"] == "high"


def test_review_approve_and_dismiss(api):
    ctx, client = api()
    reviews = {r["section_heading"]: r for r in client.get("/api/v1/reviews").json()}
    yoga = reviews["요가"]
    assert yoga["kind"] == "new_item" and yoga["can_approve"]
    r = client.post(f"/api/v1/reviews/{yoga['id']}/resolve", json={"action": "approve"})
    assert r.json()["state"] == "approved"
    dates = [o["due_date"] for o in _agenda(client, "p2", 7) if o["title"] == "요가"]
    assert dates == ["2026-10-13", "2026-10-15"]  # 화·목

    boiler = reviews["보일러 점검"]
    client.post(f"/api/v1/reviews/{boiler['id']}/resolve", json={"action": "dismiss"})
    cards = {c["heading"]: c for c in client.get("/api/v1/people/p3/notes/analysis").json()["sections"]}
    assert cards["보일러 점검"]["status"] == "ignored"


def test_rule_change_needs_approval(api):
    ctx, client = api()
    doc = _note(client, "p1")
    r = _save(client, "p1", doc["content"].replace("5주에 1번", "4주에 1번"), doc["hash"])
    assert r.status_code == 200
    ctx.extraction.run_pending()
    review = next(x for x in client.get("/api/v1/reviews", params={"people": "p1"}).json() if x["kind"] == "rule_change")
    assert review["before"]["rule"]["every"] == 5 and review["proposed"]["rule"]["every"] == 4
    # 승인 전에는 기존 규칙(5주)으로 계속 계산한다
    assert [o["due_date"] for o in _agenda(client, "p1", 60) if o["title"] == "머리 자르기"] == ["2026-11-14"]
    client.post(f"/api/v1/reviews/{review['id']}/resolve", json={"action": "approve"})
    assert [o["due_date"] for o in _agenda(client, "p1", 60) if o["title"] == "머리 자르기"][0] == "2026-11-07"


def test_write_fails_safely_when_section_renamed(api):
    ctx, client = api()
    occ = next(o for o in _agenda(client, "p2") if o["title"] == "적금 납입")
    text, _ = ctx.notes.read("p2")
    ctx.notes.write("p2", text.replace("## 적금 납입", "## 적금"), "외부 편집")  # 인덱스는 아직 모름
    r = client.post(f"/api/v1/occurrences/{occ['id']}/complete", json={})
    assert r.status_code == 409 and r.json()["review_id"]
    assert "## 적금\n" in ctx.notes.read("p2")[0] and "(대시보드)" not in ctx.notes.read("p2")[0]


def test_external_edit_is_picked_up(api):
    ctx, client = api()
    text, _ = ctx.notes.read("p3")
    ctx.notes.write("p3", text + "\n## 화분\n4주마다 화분 물주기. 10월 3일에 줌\n", "외부 편집기")
    ctx.indexer.sync_person("p3")  # 운영에서는 watchdog이 부른다
    ctx.extraction.run_pending()
    assert [o["due_date"] for o in _agenda(client, "p3", 60) if o["title"] == "화분"] == ["2026-10-31", "2026-11-28"]


def test_auth_required(api):
    ctx, client = api(overrides={"AUTH_REQUIRED": "true"})
    assert client.get("/api/v1/people").status_code == 401
    token = TokenStore(ctx.settings.data_dir / "tokens.json").create("거실태블릿")
    assert client.get("/api/v1/people", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/api/v1/people", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_morning_summary_goes_to_app_channel_once(api):
    ctx, client = api()
    assert client.post("/api/v1/admin/jobs/morning").json()["result"] == 3
    assert client.post("/api/v1/admin/jobs/morning").json()["result"] == 0  # 같은 날 두 번 보내지 않는다
    notes = client.get("/api/v1/notifications", params={"people": "p2"}).json()
    assert notes[0]["kind"] == "summary" and "적금 납입" in notes[0]["body"]
