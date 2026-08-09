import json
from datetime import datetime
from pathlib import Path
import socket
from zoneinfo import ZoneInfo

import httpx
import pytest

from ai_digest.classifiers.fixed import FixedClassifier
from ai_digest.domain import DigestError, ExtractedArticle, SummaryDraft, SummaryRecord
from ai_digest.extractors.web import WebExtractor
from ai_digest.storage import SummaryRepository
from ai_digest.summarizers.base import Summarizer
from ai_digest.workflow import AddArticleWorkflow


FIXTURE = (Path(__file__).parent / "fixtures" / "article.html").read_text(encoding="utf-8")
NOW = datetime(2026, 8, 9, 14, 0, tzinfo=ZoneInfo("Asia/Taipei"))


class DeterministicSummarizer:
    def summarize(self, article: ExtractedArticle) -> SummaryDraft:
        return SummaryDraft(
            summary="這是一段可重現的繁體中文摘要。",
            keyPoints=["公共服務採用人工智慧", "導入過程重視資料品質", "應持續評估實際成效"],
            tags=["人工智慧", "公共服務"],
            editorial="技術效益應與透明治理一併檢視。",
        )


def test_local_fixture_runs_through_real_extractor_to_valid_published_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=FIXTURE,
        )
    )
    extractor = WebExtractor(lambda: httpx.Client(transport=transport))
    summarizer: Summarizer = DeterministicSummarizer()
    repository = SummaryRepository(tmp_path)
    workflow = AddArticleWorkflow(
        extractor,
        summarizer,
        FixedClassifier("人工智慧"),
        repository,
    )

    record = workflow.run("https://example.com/article", NOW)

    paths = list(tmp_path.glob("*.json"))
    assert len(paths) == 1
    saved = SummaryRecord.model_validate(json.loads(paths[0].read_text(encoding="utf-8")))
    assert saved == record
    assert saved.status == "published"
    assert saved.source_type == "web"

    with pytest.raises(DigestError) as raised:
        workflow.run("https://example.com/article", NOW)

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "save",
        "DUPLICATE_URL",
        False,
    )
    assert list(tmp_path.glob("*.json")) == paths
