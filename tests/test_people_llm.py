"""사람 관리(화면에서 추가·수정·삭제)와 LLM 상태 불."""

import json

from app.extraction.clients.ollama import Node, OllamaClient
from tests.fake_ollama import FakeOllamaServer
from tests.fake_ollama.server import dead_url

MODEL = "qwen2.5:7b-instruct"


def test_add_person_creates_note_and_shows_up(api):
    ctx, client = api()
    r = client.post("/api/v1/people", json={"name": "하린"})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["id"] == "p4" and p["color"] and p["note_path"] == "people/p4/notes.md"
    assert ctx.notes.read("p4")[0].startswith("# 하린의 노트")
    saved = json.loads((ctx.settings.data_dir / "people.json").read_text(encoding="utf-8"))
    assert [x["name"] for x in saved["people"]][-1] == "하린"
    assert any(x["id"] == "p4" for x in client.get("/api/v1/people").json())
    assert client.get("/api/v1/agenda", params={"people": "p4"}).status_code == 200


def test_person_name_rules(api):
    ctx, client = api()
    assert client.post("/api/v1/people", json={"name": "수아"}).status_code == 409  # 중복
    assert client.post("/api/v1/people", json={"name": "김 수아"}).status_code == 409  # 공백
    assert client.post("/api/v1/people", json={"name": "수아·민"}).status_code == 409  # 공동 줄 구분자
    assert client.post("/api/v1/people", json={"name": ""}).status_code == 422


def test_rename_warns_about_shared_lines_and_keeps_human_text(api):
    ctx, client = api()
    before = ctx.notes.read("p1")[0]
    r = client.patch("/api/v1/people/p2", json={"name": "수아리", "color": "#123456"})
    assert r.status_code == 200
    body = r.json()
    assert body["person"]["name"] == "수아리" and body["person"]["color_dark"] != "#123456"
    assert body["warnings"] and "아파트 관리비" in body["warnings"][0]
    assert ctx.notes.read("p1")[0] == before  # 사람의 문장은 앱이 고치지 않는다
    # (공동: 수아) 줄이 더는 맞지 않으므로 관리비는 지훈 혼자 담당
    items = [o for o in client.get("/api/v1/agenda", params={"people": "p1", "days": 30}).json()["people"][0]["occurrences"]
             if o["title"] == "아파트 관리비"]
    assert items and items[0]["assignees"] == ["p1"]


def test_delete_person_archives_note(api):
    ctx, client = api()
    r = client.delete("/api/v1/people/p2")
    assert r.status_code == 200
    archived = r.json()["archived_to"]
    assert archived.startswith("people/_archive/p2-")
    assert (ctx.settings.data_dir / archived / "notes.md").exists()
    assert not (ctx.settings.data_dir / "people" / "p2").exists()
    assert [p["id"] for p in client.get("/api/v1/people").json()] == ["p1", "p3"]
    assert client.get("/api/v1/reviews", params={"people": "p2"}).status_code == 404
    # 관리비 공동 담당에서 빠졌다는 안내
    assert "아파트 관리비" in r.json()["warnings"][0]
    ctx.indexer.sync_person("p2")  # 파일 감시가 늦게 불러도 노트를 다시 만들지 않는다
    assert not (ctx.settings.data_dir / "people" / "p2").exists()


def test_cannot_delete_last_person(api):
    ctx, client = api(people=[{"id": "kim", "name": "김"}])
    assert client.delete("/api/v1/people/kim").status_code == 409


def test_llm_light_red_then_green(make_ctx):
    from fastapi.testclient import TestClient

    from app.main import create_app

    client_llm = OllamaClient([Node(dead_url(), MODEL)], health_timeout=0.5)
    ctx = make_ctx(client=client_llm)  # 예시 데이터 16개 섹션
    with TestClient(create_app(ctx=ctx)) as client:
        st = client.get("/api/v1/llm").json()
        assert st["available"] is False and st["pending"] == 16
        assert st["nodes"][0]["reachable"] is False and st["nodes"][0]["error"] == "응답 없음"
        assert client.get("/api/v1/agenda").status_code == 200  # 대시보드는 그대로

        with FakeOllamaServer() as srv:
            client_llm.nodes = [Node(dead_url(), MODEL), Node(srv.url, MODEL)]
            st = client.post("/api/v1/llm/check").json()
            assert st["available"] is True and st["endpoint"] == srv.url
            assert [n["reachable"] for n in st["nodes"]] == [False, True]
            ctx.extraction.run_pending()
            assert client.get("/api/v1/llm").json()["pending"] == 0


def test_llm_down_is_not_called_for_every_section(make_ctx):
    calls = {"n": 0}

    class Down(OllamaClient):
        def extract(self, section):
            calls["n"] += 1
            return super().extract(section)

    make_ctx(client=Down([Node(dead_url(), MODEL)], health_timeout=0.5))
    assert calls["n"] == 0  # 꺼진 걸 확인한 뒤로는 섹션마다 부르지 않는다


def test_model_missing_is_reported(make_ctx):
    with FakeOllamaServer(models=("llama3:8b",)) as srv:
        ctx = make_ctx(people=[{"id": "kim", "name": "김"}], client=OllamaClient([Node(srv.url, MODEL)]))
        assert ctx.extraction.check_health() is False
        node = ctx.extraction.llm_status()["nodes"][0]
        assert node["reachable"] is True and node["has_model"] is False and "ollama pull" in node["error"]
