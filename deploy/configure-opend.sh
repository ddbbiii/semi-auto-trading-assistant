#!/usr/bin/env bash
set -euo pipefail

config=/opt/trading-assistant/opend/FutuOpenD.xml
runtime_env=/etc/trading-assistant/trading-assistant.env

if [[ $EUID -ne 0 ]]; then
  echo "请以 root 身份运行此配置助手。"
  exit 1
fi

echo ""
echo "OpenD 安全配置"
echo "- 请输入富途牛牛号、注册邮箱或带区号手机号。"
echo "- 密码不会回显，也不会写入终端历史。"
echo "- 不要输入交易密码。"
echo ""
read -r -p "富途登录账号: " account
read -r -s -p "富途登录密码: " password
echo ""

if [[ -z $account || -z $password ]]; then
  echo "账号和密码不能为空。"
  exit 1
fi

password_md5=$(printf '%s' "$password" | md5sum | cut -d' ' -f1)
unset password
export FUTU_ACCOUNT="$account" FUTU_PASSWORD_MD5="$password_md5"

python3 - <<'PY'
from html import escape
import os
from pathlib import Path
import re

path = Path("/opt/trading-assistant/opend/FutuOpenD.xml")
text = path.read_text(encoding="utf-8-sig")
account = escape(os.environ["FUTU_ACCOUNT"])
password_md5 = os.environ["FUTU_PASSWORD_MD5"]
text = re.sub(r"<login_account>.*?</login_account>", f"<login_account>{account}</login_account>", text, count=1)
text = re.sub(
    r"(?:<!--\s*)?<login_pwd_md5>.*?</login_pwd_md5>(?:\s*-->)?",
    f"<login_pwd_md5>{password_md5}</login_pwd_md5>",
    text,
    count=1,
)
text = re.sub(r"<login_pwd>.*?</login_pwd>", "<login_pwd></login_pwd>", text, count=1)
path.write_text(text, encoding="utf-8")
PY
unset FUTU_ACCOUNT FUTU_PASSWORD_MD5 password_md5 account
chown trading-assistant:trading-assistant "$config"
chmod 600 "$config"

systemctl stop trading-assistant-opend.service 2>/dev/null || true
echo ""
echo "即将以前台模式启动 OpenD。"
echo "如果提示手机验证，请依次输入："
echo "  req_phone_verify_code"
echo "  input_phone_verify_code -code=你收到的验证码"
echo "看到 Ready/登录成功后输入 exit，让助手切换为后台服务。"
echo ""

set +e
sudo -H -u trading-assistant /opt/trading-assistant/opend/FutuOpenD \
  -cfg_file="$config" -api_ip=127.0.0.1 -api_port=11111 -console=1 -no_monitor=1
foreground_status=$?
set -e
echo "前台 OpenD 已退出（状态码 $foreground_status），正在启动 systemd 服务……"

systemctl enable --now trading-assistant-opend.service
for _ in {1..20}; do
  if ss -lnt | grep -q '127.0.0.1:11111'; then
    break
  fi
  sleep 1
done

if ! ss -lnt | grep -q '127.0.0.1:11111'; then
  echo "OpenD 未监听 11111。请不要重复输入密码，把本窗口中的错误信息告诉 Codex。"
  systemctl --no-pager --full status trading-assistant-opend.service || true
  exit 1
fi

sed -i 's/^TRADING_ASSISTANT_FUTU_ENABLED=.*/TRADING_ASSISTANT_FUTU_ENABLED=1/' "$runtime_env"
systemctl restart trading-assistant-api.service
sleep 3

echo ""
echo "当前系统状态："
curl -fsS http://127.0.0.1:8765/api/v1/system/status || true
echo ""
echo "配置流程完成。请回到 Codex 并回复：OpenD 配置完成"
