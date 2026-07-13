from __future__ import annotations

import base64
from io import BytesIO
import json
import os
import re
from typing import Any
from uuid import uuid4

import httpx
from PIL import Image

from .llm import _extract_responses_text, status as llm_status
from .schemas import HoldingInput, ImportPreview


VISION_PROMPT = """读取这些券商持仓截图并生成待人工确认的数据。
只提取完整可见的持仓行，不推测底部、顶部或横向被裁掉的行。多张图有重叠时按证券代码合并。
港股代码补 .HK；A 股代码补 .SZ 或 .SH。每个标的第一行通常是名称、市值、现价，第二行是代码、数量、成本。
用“市值约等于数量乘以现价”检查抄录错误。名称被省略号截断时按可见名称填写，不补写未知内容。
warnings 只写缺失、裁切、冲突或不确定项，不要写“校验正常”之类的确认语句。
严格只返回一个 JSON 对象，不要 Markdown：
{"declared_holding_count":整数或null,"holdings":[{"symbol":"字符串","name":"字符串","market":"US或HK或CN","security_type":"stock或etf或warrant","quantity":数字,"available_quantity":数字或null,"market_value":数字,"price":数字,"average_cost":数字}],"warnings":["字符串"]}
"""


def vision_import_enabled() -> bool:
    return os.getenv("TRADING_ASSISTANT_VISION_IMPORT_ENABLED", "0") == "1" and llm_status()["status"] == "configured"


def preview_images_with_vision(files: list[tuple[str, str | None, bytes]]) -> ImportPreview:
    if not files:
        raise ValueError("至少需要一张截图。")
    if len(files) > 8:
        raise ValueError("一次最多识别 8 张截图。")
    if not vision_import_enabled():
        raise RuntimeError("视觉识别未启用。")

    content: list[dict[str, Any]] = [{"type": "input_text", "text": VISION_PROMPT}]
    for file_name, content_type, data in files:
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{_prepare_image(data, file_name, content_type)}",
            }
        )

    base_url = os.environ["TRADING_ASSISTANT_LLM_BASE_URL"].rstrip("/")
    api_style = os.getenv("TRADING_ASSISTANT_LLM_API_STYLE", "chat_completions")
    if api_style == "responses":
        endpoint = f"{base_url}/responses"
        payload = {
            "model": os.environ["TRADING_ASSISTANT_LLM_MODEL"],
            "input": [{"role": "user", "content": content}],
        }
    else:
        endpoint = f"{base_url}/chat/completions"
        chat_content = [
            {"type": "text", "text": VISION_PROMPT},
            *[
                {"type": "image_url", "image_url": {"url": item["image_url"]}}
                for item in content
                if item["type"] == "input_image"
            ],
        ]
        payload = {
            "model": os.environ["TRADING_ASSISTANT_LLM_MODEL"],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": chat_content}],
        }

    response = httpx.post(
        endpoint,
        headers={"Authorization": f"Bearer {os.environ['TRADING_ASSISTANT_LLM_API_KEY']}"},
        json=payload,
        timeout=90,
    )
    response.raise_for_status()
    body = response.json()
    text = _extract_responses_text(body) if api_style == "responses" else body["choices"][0]["message"]["content"]
    parsed = _parse_json_object(text)
    holdings, validation_warnings = _validate_holdings(parsed.get("holdings"))
    if not holdings:
        raise ValueError("视觉模型没有返回可确认的完整持仓。")

    declared_count = parsed.get("declared_holding_count")
    declared_count = int(declared_count) if isinstance(declared_count, (int, float)) and declared_count > 0 else None
    warnings = [str(item) for item in parsed.get("warnings", []) if str(item).strip()]
    if declared_count:
        warnings = [
            warning
            for warning in warnings
            if not (
                "持仓" in warning
                and ("总数" in warning or "声明" in warning)
                and ("提取" in warning or "完整" in warning)
            )
        ]
    warnings.extend(validation_warnings)
    if declared_count and len(holdings) < declared_count:
        warnings.append(
            f"截图显示账户共 {declared_count} 条持仓，视觉模型只提取出 {len(holdings)} 条完整记录；"
            f"还缺 {declared_count - len(holdings)} 条，请补充未完整显示的截图。"
        )

    return ImportPreview(
        import_id=uuid4().hex,
        file_name=f"{len(files)} 张账户截图" if len(files) > 1 else files[0][0],
        parser="vision_model",
        account={"declared_holding_count": declared_count} if declared_count else {},
        holdings=holdings,
        warnings=list(dict.fromkeys(warnings)),
    )


def _prepare_image(data: bytes, file_name: str, content_type: str | None) -> str:
    if len(data) > 10 * 1024 * 1024:
        raise ValueError(f"{file_name} 超过 10 MB。")
    if not (content_type or "").startswith("image/") and not file_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        raise ValueError(f"{file_name} 不是支持的图片格式。")
    image = Image.open(BytesIO(data)).convert("RGB")
    if image.width * image.height > 40_000_000:
        raise ValueError(f"{file_name} 的像素尺寸过大。")
    image.thumbnail((1600, 2800))
    output = BytesIO()
    image.save(output, format="JPEG", quality=84, optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def _parse_json_object(value: str) -> dict[str, Any]:
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("视觉模型没有返回 JSON 对象。")
    parsed = json.loads(value[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("视觉模型返回格式无效。")
    return parsed


def _validate_holdings(value: Any) -> tuple[list[HoldingInput], list[str]]:
    if not isinstance(value, list):
        return [], ["视觉模型未返回持仓数组。"]
    holdings: list[HoldingInput] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            warnings.append(f"视觉结果第 {index} 行格式无效，已跳过。")
            continue
        try:
            market = str(item.get("market") or "").upper()
            symbol = _normalize_symbol(str(item.get("symbol") or ""), market)
            if not symbol or market not in {"US", "HK", "CN"}:
                raise ValueError("代码或市场无效")
            if symbol in seen:
                warnings.append(f"{symbol} 在多张截图中重复出现，已自动合并。")
                continue
            quantity = float(item.get("quantity"))
            market_value = float(item.get("market_value"))
            price = float(item.get("price"))
            average_cost = float(item.get("average_cost"))
            if min(quantity, market_value, price, average_cost) < 0:
                raise ValueError("数值不能为负数")
            if quantity > 0:
                consistency_error = abs(market_value - quantity * price) / max(market_value, quantity * price, 1)
                if consistency_error > 0.03:
                    warnings.append(f"{symbol} 的市值与数量×现价相差较大，请重点核对。")
            security_type = str(item.get("security_type") or "stock").lower()
            if security_type not in {"stock", "etf", "warrant"}:
                warnings.append(f"{symbol} 的证券类型无法确认，暂按股票处理。")
                security_type = "stock"
            holdings.append(
                HoldingInput(
                    symbol=symbol,
                    name=str(item.get("name") or "").strip(),
                    market=market,  # type: ignore[arg-type]
                    security_type=security_type,
                    quantity=quantity,
                    available_quantity=_optional_float(item.get("available_quantity")),
                    currency={"HK": "HKD", "CN": "CNY"}.get(market, "USD"),  # type: ignore[arg-type]
                    market_value=market_value,
                    price=price,
                    average_cost=average_cost,
                )
            )
            seen.add(symbol)
        except (TypeError, ValueError) as exc:
            warnings.append(f"视觉结果第 {index} 行无法验证（{exc}），已跳过。")
    return holdings, warnings


def _normalize_symbol(value: str, market: str) -> str:
    symbol = value.strip().upper()
    if market == "HK":
        digits = symbol.removesuffix(".HK")
        return f"{digits.zfill(5)}.HK" if digits.isdigit() and len(digits) <= 5 else ""
    if market == "CN":
        if symbol.endswith((".SZ", ".SH", ".SS")):
            return symbol
        return f"{symbol}.SZ" if symbol.isdigit() and len(symbol) == 6 else ""
    return symbol if re.fullmatch(r"[A-Z0-9.-]{1,10}", symbol) else ""


def _optional_float(value: Any) -> float | None:
    return None if value in (None, "") else float(value)
