from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
import json
import os
import re
from typing import Any, Iterable

import httpx


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FUND_TICKERS_URL = "https://www.sec.gov/files/company_tickers_mf.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_DOCUMENT_BASE_URL = "https://static.cninfo.com.cn/"
HKEX_PREFIX_URL = "https://www1.hkexnews.hk/search/prefix.do"
HKEX_SEARCH_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en"
HKEX_DOCUMENT_BASE_URL = "https://www1.hkexnews.hk"

DEFAULT_LOOKBACK_DAYS = 180
DEFAULT_TIMEOUT_SECONDS = 15.0
OFFICIAL_PROVIDERS = {"sec_edgar", "cninfo", "hkexnews"}
SEC_RELEVANT_FORMS = {
    "10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A",
    "20-F", "20-F/A", "6-K", "40-F", "40-F/A",
    "N-CSR", "N-CSRS", "N-PORT-P", "N-PX", "DEF 14A", "DEFA14A",
    "S-1", "S-1/A", "S-3", "S-3/A", "424B2", "424B3", "424B5",
}


@dataclass(frozen=True)
class OfficialEvidenceResult:
    symbol: str
    provider: str
    status: str
    detail: str
    checked_at: datetime
    events: tuple[dict[str, Any], ...] = ()

    def payload(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "provider": self.provider,
            "status": self.status,
            "detail": self.detail,
            "checked_at": self.checked_at.isoformat(),
            "events": list(self.events),
        }


def refresh_official_evidence(
    holdings: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    client: httpx.Client | None = None,
) -> list[OfficialEvidenceResult]:
    """Query official disclosure sources for active holdings without failing the full refresh."""

    now = _aware(now or datetime.now(timezone.utc))
    if os.getenv("TRADING_ASSISTANT_OFFICIAL_EVIDENCE_ENABLED", "1") != "1":
        return [
            OfficialEvidenceResult(
                symbol=_symbol(item),
                provider=_provider_for_holding(item),
                status="disabled",
                detail="官方公告采集已在环境配置中关闭。",
                checked_at=now,
            )
            for item in _active_unique_holdings(holdings)
        ]

    own_client = client is None
    http = client or httpx.Client(
        timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS, connect=8),
        follow_redirects=True,
        headers={"User-Agent": "OpenStock/0.1 official-evidence-collector"},
    )
    results: list[OfficialEvidenceResult] = []
    sec_tickers: dict[str, int] | None = None
    lookback_days = max(7, int(os.getenv("TRADING_ASSISTANT_OFFICIAL_EVIDENCE_LOOKBACK_DAYS", str(DEFAULT_LOOKBACK_DAYS))))
    try:
        for holding in _active_unique_holdings(holdings):
            symbol = _symbol(holding)
            provider = _provider_for_holding(holding)
            try:
                if provider == "sec_edgar":
                    if sec_tickers is None:
                        sec_tickers = _load_sec_tickers(http)
                    result = _fetch_sec(symbol, sec_tickers, http, now, lookback_days)
                elif provider == "cninfo":
                    result = _fetch_cninfo(symbol, http, now, lookback_days)
                elif provider == "hkexnews":
                    result = _fetch_hkex(symbol, http, now, lookback_days)
                else:
                    result = OfficialEvidenceResult(
                        symbol=symbol,
                        provider=provider,
                        status="unsupported",
                        detail="当前市场尚无已配置的官方公告来源。",
                        checked_at=now,
                    )
            except Exception as exc:
                result = OfficialEvidenceResult(
                    symbol=symbol,
                    provider=provider,
                    status="failed",
                    detail=_safe_error(exc),
                    checked_at=now,
                )
            results.append(result)
    finally:
        if own_client:
            http.close()
    return results


def _load_sec_tickers(client: httpx.Client) -> dict[str, int]:
    user_agent = os.getenv(
        "TRADING_ASSISTANT_SEC_USER_AGENT",
        "OpenStock personal-investment-desk contact@example.invalid",
    )
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    company_response = client.get(SEC_TICKERS_URL, headers=headers)
    company_response.raise_for_status()
    company_payload = company_response.json()
    tickers = {
        str(item.get("ticker") or "").upper(): int(item["cik_str"])
        for item in company_payload.values()
        if isinstance(item, dict) and item.get("ticker") and item.get("cik_str") is not None
    }

    fund_response = client.get(SEC_FUND_TICKERS_URL, headers=headers)
    fund_response.raise_for_status()
    fund_payload = fund_response.json()
    fields = list(fund_payload.get("fields") or [])
    if "cik" in fields and "symbol" in fields:
        cik_index = fields.index("cik")
        symbol_index = fields.index("symbol")
        for row in fund_payload.get("data") or []:
            if isinstance(row, list) and len(row) > max(cik_index, symbol_index):
                tickers.setdefault(str(row[symbol_index]).upper(), int(row[cik_index]))
    return tickers


def _fetch_sec(
    symbol: str,
    tickers: dict[str, int],
    client: httpx.Client,
    now: datetime,
    lookback_days: int,
) -> OfficialEvidenceResult:
    ticker = symbol.split(".", 1)[0].replace(".", "-").upper()
    cik = tickers.get(ticker)
    if cik is None:
        return OfficialEvidenceResult(symbol, "sec_edgar", "failed", "SEC 未找到该代码对应的 CIK。", now)

    user_agent = os.getenv(
        "TRADING_ASSISTANT_SEC_USER_AGENT",
        "OpenStock personal-investment-desk contact@example.invalid",
    )
    response = client.get(
        SEC_SUBMISSIONS_URL.format(cik=cik),
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
    )
    response.raise_for_status()
    payload = response.json()
    recent = ((payload.get("filings") or {}).get("recent") or {})
    cutoff = now - timedelta(days=lookback_days)
    events: list[dict[str, Any]] = []
    forms = recent.get("form") or []
    for index, form_value in enumerate(forms):
        form = str(form_value or "").upper()
        if form not in SEC_RELEVANT_FORMS:
            continue
        filing_date = _list_value(recent, "filingDate", index)
        observed_at = _parse_date(filing_date)
        if observed_at is None or observed_at < cutoff:
            continue
        accession = str(_list_value(recent, "accessionNumber", index) or "")
        primary_document = str(_list_value(recent, "primaryDocument", index) or "")
        if not accession or not primary_document:
            continue
        accession_path = accession.replace("-", "")
        source_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/{primary_document}"
        events.append(
            {
                "external_id": accession,
                "kind": "filing",
                "title": f"{form} · {payload.get('name') or ticker}",
                "detail": "SEC EDGAR 官方申报文件",
                "source_url": source_url,
                "observed_at": observed_at.isoformat(),
                "form": form,
            }
        )
        if len(events) >= 12:
            break
    return OfficialEvidenceResult(
        symbol,
        "sec_edgar",
        "ok",
        f"SEC EDGAR 查询成功，近 {lookback_days} 天找到 {len(events)} 条相关文件。",
        now,
        tuple(events),
    )


def _fetch_cninfo(
    symbol: str,
    client: httpx.Client,
    now: datetime,
    lookback_days: int,
) -> OfficialEvidenceResult:
    code = re.sub(r"\D", "", symbol.split(".", 1)[0])
    suffix = symbol.upper().rsplit(".", 1)[-1] if "." in symbol else "SZ"
    is_shanghai = suffix in {"SS", "SH"} or code.startswith(("5", "6", "9"))
    start = (now - timedelta(days=lookback_days)).date().isoformat()
    end = now.date().isoformat()
    response = client.post(
        CNINFO_QUERY_URL,
        headers={
            "User-Agent": "Mozilla/5.0 OpenStock official-evidence-collector",
            "Referer": "https://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
        },
        data={
            "pageNum": "1",
            "pageSize": "30",
            "column": "sse" if is_shanghai else "szse",
            "tabName": "fulltext",
            "plate": "sh" if is_shanghai else "sz",
            "stock": "",
            "searchkey": code,
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": f"{start}~{end}",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        },
    )
    response.raise_for_status()
    payload = response.json()
    events = []
    for item in payload.get("announcements") or []:
        if str(item.get("secCode") or "") != code:
            continue
        observed_at = _from_epoch_milliseconds(item.get("announcementTime"))
        adjunct = str(item.get("adjunctUrl") or "").lstrip("/")
        if observed_at is None or not adjunct:
            continue
        events.append(
            {
                "external_id": str(item.get("announcementId") or adjunct),
                "kind": "filing",
                "title": _clean_html(item.get("announcementTitle") or item.get("shortTitle") or "公司公告"),
                "detail": "巨潮资讯官方公告",
                "source_url": CNINFO_DOCUMENT_BASE_URL + adjunct,
                "observed_at": observed_at.isoformat(),
            }
        )
        if len(events) >= 12:
            break
    return OfficialEvidenceResult(
        symbol,
        "cninfo",
        "ok",
        f"巨潮资讯查询成功，近 {lookback_days} 天找到 {len(events)} 条公告。",
        now,
        tuple(events),
    )


def _fetch_hkex(
    symbol: str,
    client: httpx.Client,
    now: datetime,
    lookback_days: int,
) -> OfficialEvidenceResult:
    code = re.sub(r"\D", "", symbol.split(".", 1)[0]).zfill(5)
    prefix_response = client.get(
        HKEX_PREFIX_URL,
        params={"callback": "callback", "lang": "EN", "type": "A", "name": code, "market": "SEHK"},
        headers={"Referer": HKEX_SEARCH_URL, "User-Agent": "Mozilla/5.0 OpenStock"},
    )
    prefix_response.raise_for_status()
    match = re.search(r"callback\((\{.*\})\)\s*;?", prefix_response.text, re.DOTALL)
    if not match:
        raise ValueError("港交所代码查询返回格式无法识别。")
    stock_rows = json.loads(match.group(1)).get("stockInfo") or []
    stock_row = next((item for item in stock_rows if str(item.get("code") or "").zfill(5) == code), None)
    if not stock_row:
        return OfficialEvidenceResult(symbol, "hkexnews", "failed", "港交所披露易未找到该证券代码。", now)

    start = (now - timedelta(days=lookback_days)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    response = client.post(
        HKEX_SEARCH_URL,
        headers={"Referer": HKEX_SEARCH_URL, "User-Agent": "Mozilla/5.0 OpenStock"},
        data={
            "lang": "EN",
            "category": "0",
            "market": "SEHK",
            "searchType": "0",
            "documentType": "-1",
            "t1code": "-2",
            "t2Gcode": "-2",
            "t2code": "-2",
            "stockId": str(stock_row["stockId"]),
            "from": start,
            "to": end,
        },
    )
    response.raise_for_status()
    parser = _HKEXResultParser()
    parser.feed(response.text)
    events = parser.events[:12]
    return OfficialEvidenceResult(
        symbol,
        "hkexnews",
        "ok",
        f"港交所披露易查询成功，近 {lookback_days} 天找到 {len(events)} 条公告。",
        now,
        tuple(events),
    )


class _HKEXResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[dict[str, Any]] = []
        self._row: dict[str, Any] | None = None
        self._capture: str | None = None
        self._text: list[str] = []
        self._anchor_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if tag == "tr":
            self._row = {}
        elif self._row is not None and tag == "td" and "release-time" in classes:
            self._capture = "release_time"
            self._text = []
        elif self._row is not None and tag == "div" and "headline" in classes:
            self._capture = "headline"
            self._text = []
        elif self._row is not None and tag == "a" and attributes.get("href", "").lower().endswith(".pdf"):
            self._capture = "document_title"
            self._text = []
            self._anchor_url = attributes["href"]

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._row is not None and tag in {"td", "div", "a"} and self._capture:
            text = _collapse_space(" ".join(self._text))
            if self._capture == "document_title" and tag == "a":
                self._row["title"] = text
                self._row["source_url"] = _absolute_hkex_url(self._anchor_url or "")
                self._capture = None
            elif self._capture == "headline" and tag == "div":
                self._row["headline"] = text
                self._capture = None
            elif self._capture == "release_time" and tag == "td":
                self._row["release_time"] = text
                self._capture = None
            if self._capture is None:
                self._text = []
        if tag == "tr" and self._row is not None:
            event = _hkex_row_event(self._row)
            if event:
                self.events.append(event)
            self._row = None
            self._capture = None
            self._text = []
            self._anchor_url = None


def _hkex_row_event(row: dict[str, Any]) -> dict[str, Any] | None:
    source_url = str(row.get("source_url") or "")
    if not source_url:
        return None
    observed_at = _parse_hkex_datetime(str(row.get("release_time") or ""))
    if observed_at is None:
        return None
    title = str(row.get("title") or row.get("headline") or "公司公告")
    return {
        "external_id": source_url.rsplit("/", 1)[-1].removesuffix(".pdf"),
        "kind": "filing",
        "title": title,
        "detail": f"港交所披露易 · {row.get('headline') or '上市公司文件'}",
        "source_url": source_url,
        "observed_at": observed_at.isoformat(),
    }


def _active_unique_holdings(holdings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in holdings:
        symbol = _symbol(item)
        if not symbol or symbol in seen or float(item.get("quantity") or 0) <= 0:
            continue
        result.append(item)
        seen.add(symbol)
    return result


def _provider_for_holding(holding: dict[str, Any]) -> str:
    symbol = _symbol(holding)
    market = str(holding.get("market") or "").upper()
    if market == "HK" or symbol.endswith(".HK"):
        return "hkexnews"
    if market in {"CN", "A"} or symbol.endswith((".SZ", ".SS", ".SH")):
        return "cninfo"
    if market == "US" or "." not in symbol:
        return "sec_edgar"
    return "unsupported"


def _symbol(holding: dict[str, Any]) -> str:
    return str(holding.get("symbol") or "").strip().upper()


def _list_value(payload: dict[str, Any], key: str, index: int) -> Any:
    values = payload.get(key) or []
    return values[index] if index < len(values) else None


def _parse_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _from_epoch_milliseconds(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _parse_hkex_datetime(value: str) -> datetime | None:
    match = re.search(r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", value)
    if not match:
        return None
    try:
        local = datetime.strptime(match.group(1), "%d/%m/%Y %H:%M")
        return local.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
    except ValueError:
        return None


def _clean_html(value: Any) -> str:
    return _collapse_space(re.sub(r"<[^>]+>", "", unescape(str(value or ""))))


def _collapse_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _absolute_hkex_url(value: str) -> str:
    return value if value.startswith("http") else HKEX_DOCUMENT_BASE_URL + "/" + value.lstrip("/")


def _safe_error(exc: Exception) -> str:
    message = _collapse_space(str(exc)) or exc.__class__.__name__
    return f"官方来源查询失败：{message[:240]}"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
