"""
週1回（毎週月曜 日本時間）、直近5営業日分のシグナル状況をダイジェスト通知
する。ゴールデンクロス／高信頼度デッドクロスが1件もない週でも「変化なし」
を通知し、「通知が来ない＝壊れている」という不安を防ぐのが目的。

GitHub Actions から日次で呼ばれる想定。月曜以外は即座に終了する。
NTFY_TOPIC が必須。
"""

import csv
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from notify_signals import build_click_url, is_actionable, send_ntfy

SIGNALS_CSV = "ma_cross_signals.csv"


def build_digest_message(rows: list) -> str:
    actionable = [r for r in rows if is_actionable(r)]
    golden_n = sum(1 for r in actionable if r["シグナル"] == "ゴールデンクロス")
    dead_n = sum(1 for r in actionable if r["シグナル"] == "デッドクロス")

    lines = ["## 📅 週次サマリー（直近5営業日）", ""]
    if not actionable:
        lines.append("今週はゴールデンクロス／高信頼度デッドクロスとも0件でした。変化なし。")
    else:
        lines.append(f"ゴールデンクロス: {golden_n}件　高信頼度デッドクロス: {dead_n}件")
        lines.append("")
        for r in actionable:
            lines.append(f"- **{r['ティッカー']}** {r['シグナル']}（{r['発生日']}）")
    return "\n".join(lines)


def main():
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC が設定されていません。週次サマリーをスキップします。")
        return

    now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
    if now_jst.weekday() != 0:  # 0 = 月曜
        print("本日は週次サマリー対象日ではありません（月曜のみ送信）")
        return

    rows = []
    try:
        with open(SIGNALS_CSV, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        pass

    msg = build_digest_message(rows)
    print(msg)

    headers = {
        "Title": "週次サマリー",
        "Tags": "calendar",
        "Priority": "default",
        "Markdown": "yes",
    }
    click_url = build_click_url()
    if click_url:
        headers["Click"] = click_url

    status = send_ntfy(topic, data=msg.encode("utf-8"), headers=headers, method="POST")
    print(f"ntfy.sh weekly digest response: {status}")


if __name__ == "__main__":
    sys.exit(main())
