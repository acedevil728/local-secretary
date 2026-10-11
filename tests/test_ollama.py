import datetime as dt

import pytest

from app.extraction.clients.base import BadLLMOutput, LLMUnavailable
from app.extraction.clients.ollama import Node, OllamaClient
from app.extraction.clients.replay import CassetteMissing, ReplayClient
from app.extraction.schema import SectionInput
from tests.conftest import KIM
from tests.fake_ollama import FakeOllamaServer
from tests.fake_ollama.server import dead_url

MODEL = "qwen2.5:7b-instruct"
INP = SectionInput(heading="머리 자르기", text="나는 5주에 1번 머리를 잘라. 10월 10일에 잘랐음", today=dt.date(2026, 10, 10))


@pytest.fixture
def fake():
    with FakeOllamaServer() as srv:
        yield srv


def test_extracts_through_ollama_api(fake):
    client = OllamaClient([Node(fake.url, MODEL)])
    resp = client.extract(INP)
    assert resp.model == f"ollama:{MODEL}"
    assert resp.result.items[0].rule.every == 5
    req = fake.requests[-1]
    assert req["format"]["type"] == "object" and req["stream"] is False and req["options"]["temperature"] == 0


def test_first_node_down_uses_second(fake):
    client = OllamaClient([Node(dead_url(), MODEL), Node(fake.url, MODEL)], health_timeout=0.5)
    client.extract(INP)
    assert client.active_endpoint() == fake.url


def test_node_without_model_is_skipped(fake):
    with FakeOllamaServer(models=("llama3:8b",)) as other:
        client = OllamaClient([Node(other.url, MODEL), Node(fake.url, MODEL)])
        client.extract(INP)
        assert client.active_endpoint() == fake.url


def test_all_nodes_down():
    client = OllamaClient([Node(dead_url(), MODEL), Node(dead_url(), MODEL)], health_timeout=0.5)
    assert client.health() is False
    with pytest.raises(LLMUnavailable):
        client.extract(INP)


def test_slow_node_times_out_and_falls_over(fake):
    with FakeOllamaServer() as slow:
        slow.delay = 1.5
        client = OllamaClient([Node(slow.url, MODEL), Node(fake.url, MODEL)], timeout=0.5)
        client.extract(INP)
        assert client.active_endpoint() == fake.url


def test_bad_json_is_bad_output(fake):
    fake.bad_json = True
    with pytest.raises(BadLLMOutput):
        OllamaClient([Node(fake.url, MODEL)]).extract(INP)


def test_replay_records_and_replays(fake, tmp_path):
    recorder = ReplayClient(tmp_path, record_with=OllamaClient([Node(fake.url, MODEL)]))
    recorded = recorder.extract(INP)
    fake.stop()
    replayed = ReplayClient(tmp_path).extract(INP)
    assert replayed.result == recorded.result
    with pytest.raises(CassetteMissing):
        ReplayClient(tmp_path).extract(INP.model_copy(update={"text": "다른 문장"}))


def test_dashboard_works_while_llm_is_down_and_analysis_resumes(make_ctx, fake):
    client = OllamaClient([Node(dead_url(), MODEL)], health_timeout=0.5)
    ctx = make_ctx(people=KIM, client=client)
    ctx.notes.write("kim", "## 머리 자르기\n나는 5주에 1번 머리를 잘라. 2026년 10월 10일에 잘랐음\n<!-- history -->\n", "t")
    ctx.indexer.sync_person("kim")
    ctx.extraction.run_pending()
    cards = ctx.extraction.cards("kim")
    assert cards[0]["status"] == "waiting_llm"
    assert ctx.occurrences.agenda(["kim"], 14)["people"][0]["occurrences"] == []  # 대시보드는 계속 응답한다

    client.nodes = [Node(dead_url(), MODEL), Node(fake.url, MODEL)]  # 두 번째 노드가 살아남
    assert ctx.extraction.check_health()
    ctx.extraction.retry_waiting()
    ctx.extraction.run_pending()
    card = ctx.extraction.cards("kim")[0]
    assert card["status"] == "done" and card["item"]["next_date"] == "2026-11-14"
