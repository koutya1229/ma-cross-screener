"""
1458_signal_watch.py の実行後、1458_signal_watch.csv が生成されていれば
（＝直近で1458の新規買いシグナルが発生していれば）ntfy.sh 経由でプッシュ
通知する。notify_soxl_signals.py / notify_signals.py と同じ NTFY_TOPIC
シークレットを共用する（スマホ側で新しいtopicを購読し直す必要はない）。

GitHub Actions から呼ばれる想定（環境変数 NTFY_TOPIC が必須）。
"""

import csv
import os
import sys
import urllib.request

SIGNALS_CSV = "1458_signal_watch.csv"


def send_ntfy(topic: str, *, data: bytes, headers: dict, method: str = "POST") -> int:
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status


def build_message(rows: list) -> str:
    lines = ["## 1458(日経レバレッジ2倍) 買いシグナル検出", ""]
    for r in rows:
        lines.append(f"- **{r['シグナル']}** — 終値 ¥{r['終値']} (RSI {r['RSI']}, {r['発生日']})")
    lines.append("")
    lines.append(
        "_中期トレンド判定(EMA50/EMA200・RSI(14)・MACD)に基づく参考シグナルです。"
        "投資助言ではありません。_"
    )
    return "\n".join(lines)


def main() -> None:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC が設定されていません。通知をスキップします。")
        return

    try:
        with open(SIGNALS_CSV, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        print("本日は1458の新規シグナルなし（1458_signal_watch.csv が生成されませんでした）")
        return

    if not rows:
        print("本日は1458の新規シグナルなし")
        return

    msg = build_message(rows)
    print(msg)

    headers = {
        "Title": "1458 Signal Detected",
        "Tags": "rocket",
        "Priority": "high",
        "Markdown": "yes",
    }
    status = send_ntfy(topic, data=msg.encode("utf-8"), headers=headers, method="POST")
    print(f"ntfy.sh response: {status}")


if __name__ == "__main__":
    sys.exit(main())
