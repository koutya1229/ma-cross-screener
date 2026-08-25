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

CATEGORY_EMOJI = {
    "leveraged_bull": "🚀",
    "plain_etf": "📈",
    "stock": "🏢",
    "leveraged_inverse": "🔻",
}


def build_message(latest_date: str, rows: list) -> str:
    lines = [f"## 🟢 ゴールデンクロス検出（{latest_date}）", ""]
    for r in rows:
        emoji = CATEGORY_EMOJI.get(r["カテゴリ"], "•")
        lines.append(f"- {emoji} **{r['ティッカー']}** `${r['終値']}` — {r['カテゴリ']}")
    lines.append("")
    lines.append("_過去統計（2015年〜・21銘柄）ではフィルターなしで勝率55%程度。投資助言ではありません。_")
    return "\n".join(lines)


def build_click_url() -> str | None:
    server = os.environ.get("GITHUB_SERVER_URL")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return None


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

    msg = build_message(latest_date, latest)
    print(msg)

    tickers_summary = ", ".join(r["ティッカー"] for r in latest)

    headers = {
        "Title": f"Golden Cross: {tickers_summary}"[:250],
        "Tags": "rocket,chart_with_upwards_trend",
        "Priority": "high",
        "Markdown": "yes",
    }
    click_url = build_click_url()
    if click_url:
        headers["Click"] = click_url

    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=msg.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"ntfy.sh response: {resp.status}")


if __name__ == "__main__":
    sys.exit(main())
