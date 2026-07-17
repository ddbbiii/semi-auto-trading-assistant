from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile

import httpx

from trading_assistant.db import Store
from trading_assistant.official_evidence import refresh_official_evidence


NOW = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)


def test_sec_supports_company_and_fund_tickers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, json={"0": {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."}})
        if request.url.path.endswith("company_tickers_mf.json"):
            return httpx.Response(200, json={"fields": ["cik", "seriesId", "classId", "symbol"], "data": [[1100663, "S1", "C1", "SOXX"]]})
        if request.url.path.endswith("CIK0001652044.json"):
            return httpx.Response(200, json={
                "name": "Alphabet Inc.",
                "filings": {"recent": {
                    "form": ["10-Q"],
                    "filingDate": ["2026-06-01"],
                    "accessionNumber": ["0000000000-26-000001"],
                    "primaryDocument": ["report.htm"],
                }},
            })
        if request.url.path.endswith("CIK0001100663.json"):
            return httpx.Response(200, json={
                "name": "iShares Trust",
                "filings": {"recent": {
                    "form": ["N-CSR"],
                    "filingDate": ["2026-06-02"],
                    "accessionNumber": ["0000000000-26-000002"],
                    "primaryDocument": ["fund.htm"],
                }},
            })
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results = refresh_official_evidence(
            [
                {"symbol": "GOOG", "market": "US", "quantity": 1},
                {"symbol": "SOXX", "market": "US", "quantity": 1},
            ],
            now=NOW,
            client=client,
        )

    assert [item.status for item in results] == ["ok", "ok"]
    assert results[0].events[0]["title"].startswith("10-Q")
    assert results[1].events[0]["title"].startswith("N-CSR")


def test_cninfo_and_hkex_results_are_normalized() -> None:
    hkex_html = """
    <table><tr>
      <td class="release-time">17/07/2026 18:02</td>
      <td><div class="headline">Announcements and Notices - [Results]</div>
      <a href="/listedco/listconews/sehk/2026/0717/2026071700001.pdf">Interim Results</a></td>
    </tr></table>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.cninfo.com.cn":
            return httpx.Response(200, json={"announcements": [{
                "secCode": "600519",
                "announcementId": "1225000001",
                "announcementTitle": "<em>测试公司</em>2026年半年度报告",
                "announcementTime": 1784217600000,
                "adjunctUrl": "finalpage/2026-07-17/1225000001.PDF",
            }]})
        if request.url.path.endswith("prefix.do"):
            return httpx.Response(200, text='callback({"stockInfo":[{"stockId":190371,"code":"01810","name":"XIAOMI-W"}]});')
        if request.url.path.endswith("titlesearch.xhtml"):
            return httpx.Response(200, text=hkex_html)
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results = refresh_official_evidence(
            [
                {"symbol": "600519.SS", "market": "CN", "quantity": 1},
                {"symbol": "01810.HK", "market": "HK", "quantity": 1},
            ],
            now=NOW,
            client=client,
        )

    assert results[0].status == "ok"
    assert results[0].events[0]["title"] == "测试公司2026年半年度报告"
    assert results[1].status == "ok"
    assert results[1].events[0]["title"] == "Interim Results"
    assert results[1].events[0]["source_url"].startswith("https://www1.hkexnews.hk/")


def test_store_tracks_successful_checks_separately_from_document_count() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'evidence.sqlite3').as_posix()}")
        store.create_schema()
        store.save_official_evidence([
            {
                "symbol": "AAA",
                "provider": "sec_edgar",
                "status": "ok",
                "detail": "查询成功，无近期文件。",
                "checked_at": NOW.isoformat(),
                "events": [],
            },
            {
                "symbol": "BBB",
                "provider": "cninfo",
                "status": "ok",
                "detail": "查询成功。",
                "checked_at": NOW.isoformat(),
                "events": [{
                    "external_id": "1",
                    "kind": "filing",
                    "title": "半年度报告",
                    "detail": "官方公告",
                    "source_url": "https://example.invalid/1.pdf",
                    "observed_at": NOW.isoformat(),
                }],
            },
        ])
        state = store.official_evidence_state(["AAA", "BBB"], max_check_age_hours=10_000)
        store.close()

    assert state["checks"]["AAA"]["status"] == "ok"
    assert state["documents"]["AAA"] == []
    assert state["checks"]["BBB"]["fresh"] is True
    assert state["documents"]["BBB"][0]["title"] == "半年度报告"
