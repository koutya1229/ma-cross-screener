"""
ma_cross_screener.py の実行後、直近営業日に新しく発生したゴールデンクロス
（買いシグナル）があれば ntfy.sh 経由でプッシュ通知する。

GitHub Actions から呼ばれる想定（環境変数 NTFY_TOPIC が必須）。
"""

import csv
import os
import sys
import urllib.request

SIGNALS_CSV = "ma_cross_signals.csv"


def main():
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC が設定されていません。通知をスキップします。")
        return

    try:
        with open(SIGNALS_CSV, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        print("本日はシグナルなし（ma_cross_signals.csv が生成されませんでした）")
        return

    golden = [r for r in rows if r.get("シグナル") == "ゴールデンクロス"]
    if not golden:
        print("本日は新しいゴールデンクロスなし")
        return

    latest_date = max(r["発生日"] for r in golden)
    latest = [r for r in golden if r["発生日"] == latest_date]

    msg = f"ゴールデンクロス検出({latest_date}): " + ", ".join(
        f"{r['ティッカー']} ${r['終値']}" for r in latest
    )
    print(msg)

    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=msg.encode("utf-8"),
        headers={"Title": "MA Cross Screener", "Priority": "default"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"ntfy.sh response: {resp.status}")


if __name__ == "__main__":
    sys.exit(main())
