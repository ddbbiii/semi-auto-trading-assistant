from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx
from PIL import Image

from trading_assistant.api import create_app
from trading_assistant.db import Store
from trading_assistant.schemas import ImportPreview
from trading_assistant.vision import preview_images_with_vision


def image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (40, 60), "white").save(output, format="PNG")
    return output.getvalue()


def vision_payload() -> dict[str, object]:
    return {
        "declared_holding_count": 2,
        "holdings": [
            {
                "symbol": "00700",
                "name": "Tencent",
                "market": "HK",
                "security_type": "stock",
                "currency": "HKD",
                "quantity": 10,
                "available_quantity": None,
                "market_value": 3000,
                "price": 300,
                "average_cost": 280,
            },
            {
                "symbol": "AAPL",
                "name": "Apple",
                "market": "US",
                "security_type": "stock",
                "currency": "USD",
                "quantity": 5,
                "available_quantity": None,
                "market_value": 1000,
                "price": 200,
                "average_cost": 180,
            },
        ],
        "warnings": [],
    }


def test_vision_preview_uses_responses_api_and_validates_holdings() -> None:
    response = httpx.Response(
        200,
        json={"output_text": json.dumps(vision_payload(), ensure_ascii=False)},
        request=httpx.Request("POST", "https://example.test/v1/responses"),
    )
    environment = {
        "TRADING_ASSISTANT_LLM_BASE_URL": "https://example.test/v1",
        "TRADING_ASSISTANT_LLM_API_KEY": "test-key",
        "TRADING_ASSISTANT_LLM_MODEL": "test-vision",
        "TRADING_ASSISTANT_LLM_API_STYLE": "responses",
        "TRADING_ASSISTANT_VISION_IMPORT_ENABLED": "1",
    }

    with patch.dict(os.environ, environment, clear=False), patch(
        "trading_assistant.vision.httpx.post", return_value=response
    ) as post:
        preview = preview_images_with_vision([("账户.png", "image/png", image_bytes())])

    assert preview.parser == "vision_model"
    assert preview.account["declared_holding_count"] == 2
    assert [(item.symbol, item.security_type) for item in preview.holdings] == [
        ("00700.HK", "stock"),
        ("AAPL", "stock"),
    ]
    sent = post.call_args.kwargs["json"]
    assert sent["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")


def test_import_api_prefers_vision_without_committing_snapshot() -> None:
    preview = ImportPreview(
        import_id="vision-preview",
        file_name="2 张账户截图",
        parser="vision_model",
        account={"declared_holding_count": 1},
        holdings=vision_payload()["holdings"][:1],  # type: ignore[index]
        warnings=[],
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'test.sqlite3').as_posix()}")
        app = create_app(store, schedule=False)
        with patch("trading_assistant.api.vision_import_enabled", return_value=True), patch(
            "trading_assistant.api.preview_images_with_vision", return_value=preview
        ) as vision:
            with TestClient(app) as client:
                before = store.latest_snapshot()
                response = client.post(
                    "/api/v1/import/preview",
                    files=[("files", ("账户.png", image_bytes(), "image/png"))],
                )
                after = store.latest_snapshot()

    assert response.status_code == 200
    assert response.json()["parser"] == "vision_model"
    assert vision.call_count == 1
    assert before == after


def test_import_api_falls_back_to_local_ocr_when_vision_fails() -> None:
    fallback = ImportPreview(
        import_id="ocr-preview",
        file_name="账户.png",
        parser="png",
        account={},
        holdings=vision_payload()["holdings"][:1],  # type: ignore[index]
        warnings=[],
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        store = Store(f"sqlite:///{(Path(temp_dir) / 'test.sqlite3').as_posix()}")
        app = create_app(store, schedule=False)
        with patch("trading_assistant.api.vision_import_enabled", return_value=True), patch(
            "trading_assistant.api.preview_images_with_vision", side_effect=RuntimeError("provider unavailable")
        ), patch("trading_assistant.api.preview_import_batch", return_value=fallback) as local_ocr:
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/import/preview",
                    files=[("files", ("账户.png", image_bytes(), "image/png"))],
                )

    assert response.status_code == 200
    assert response.json()["parser"] == "png"
    assert response.json()["warnings"][0].startswith("视觉模型识别暂时不可用")
    assert local_ocr.call_count == 1
