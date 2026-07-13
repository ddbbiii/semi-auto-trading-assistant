#!/usr/bin/env bash
set -euo pipefail

runtime_env=/etc/trading-assistant/trading-assistant.env
python_bin=/opt/trading-assistant/venv/bin/python

if [[ $EUID -ne 0 ]]; then
  echo "请以 root 身份运行此配置助手。"
  exit 1
fi

echo ""
echo "OpenAI-compatible API 安全配置"
echo "示例 Base URL: https://api.openai.com/v1"
echo "API Key 输入时不会显示字符，也不会写入终端历史。"
echo ""
read -r -p "Base URL: " base_url
read -r -p "模型名: " model
read -r -p "API 协议 [responses/chat_completions]（默认 responses）: " api_style
read -r -s -p "API Key: " api_key
echo ""

base_url=${base_url%/}
api_style=${api_style:-responses}
if [[ ! $base_url =~ ^https?:// ]] || [[ -z $model || -z $api_key ]]; then
  echo "Base URL 必须以 http:// 或 https:// 开头，模型名和 API Key 不能为空。"
  exit 1
fi
if [[ $api_style != "responses" && $api_style != "chat_completions" ]]; then
  echo "API 协议只能是 responses 或 chat_completions。"
  exit 1
fi

export LLM_TEST_BASE_URL="$base_url" LLM_TEST_MODEL="$model" LLM_TEST_API_KEY="$api_key" LLM_TEST_API_STYLE="$api_style"
unset api_key

echo "正在使用应用的实际请求格式测试 API……"
"$python_bin" - <<'PY'
import json
import os
import sys

import httpx

api_style = os.environ["LLM_TEST_API_STYLE"]
if api_style == "responses":
    url = os.environ["LLM_TEST_BASE_URL"] + "/responses"
    payload = {"model": os.environ["LLM_TEST_MODEL"], "input": '只返回 JSON：{"status":"ok"}'}
else:
    url = os.environ["LLM_TEST_BASE_URL"] + "/chat/completions"
    payload = {
        "model": os.environ["LLM_TEST_MODEL"],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": '只返回 JSON：{"status":"ok"}'}],
    }
try:
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {os.environ['LLM_TEST_API_KEY']}"},
        json=payload,
        timeout=45,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        raise ValueError(f"服务返回的不是 JSON（HTTP {response.status_code}, Content-Type: {content_type}）")
    body = response.json()
    if api_style == "responses":
        content = body.get("output_text")
        if not isinstance(content, str):
            content = "".join(
                part.get("text", "")
                for item in body.get("output", []) if isinstance(item, dict)
                for part in item.get("content", []) if isinstance(part, dict) and part.get("type") == "output_text"
            )
    else:
        content = body["choices"][0]["message"]["content"]
    if not content:
        raise ValueError("响应中没有文本内容。")
    json.loads(content)
except Exception as exc:
    print(f"API 测试失败：{type(exc).__name__}: {exc}")
    sys.exit(1)
print("API 测试成功，模型返回了有效 JSON。")
PY

"$python_bin" - <<'PY'
from pathlib import Path
import os
import tempfile

path = Path("/etc/trading-assistant/trading-assistant.env")
updates = {
    "TRADING_ASSISTANT_LLM_BASE_URL": os.environ["LLM_TEST_BASE_URL"],
    "TRADING_ASSISTANT_LLM_API_KEY": os.environ["LLM_TEST_API_KEY"],
    "TRADING_ASSISTANT_LLM_MODEL": os.environ["LLM_TEST_MODEL"],
    "TRADING_ASSISTANT_LLM_API_STYLE": os.environ["LLM_TEST_API_STYLE"],
}
lines = path.read_text(encoding="utf-8").splitlines()
seen = set()
result = []
for line in lines:
    key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
    if key in updates:
        result.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        result.append(line)
for key, value in updates.items():
    if key not in seen:
        result.append(f"{key}={value}")

fd, temporary_name = tempfile.mkstemp(prefix="trading-assistant.env.", dir=str(path.parent), text=True)
temporary = Path(temporary_name)
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    stream.write("\n".join(result) + "\n")
temporary.chmod(0o600)
temporary.replace(path)
PY

unset LLM_TEST_BASE_URL LLM_TEST_MODEL LLM_TEST_API_KEY LLM_TEST_API_STYLE
chown root:trading-assistant "$runtime_env"
chmod 600 "$runtime_env"
systemctl restart trading-assistant-api.service
status_file=$(mktemp)
trap 'rm -f "$status_file"' EXIT
ready=0
for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:8765/api/v1/system/status >"$status_file"; then
    ready=1
    break
  fi
  sleep 1
done

echo ""
echo "当前模型状态："
if [[ $ready == 1 ]]; then
  "$python_bin" -c 'import json,sys; print(json.load(open(sys.argv[1]))["llm"])' "$status_file"
else
  echo "API 在 30 秒内未恢复，请回到 Codex 检查服务状态；模型配置已经安全写入。"
  exit 1
fi
echo ""
echo "配置完成。请回到 Codex 并回复：API 配置完成"
