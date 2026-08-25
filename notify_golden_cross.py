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
    """GitHub Pages のレポートページへのリンク（owner.github.io/repo/ 形式）。
    Pages が未設定/未反映の場合に備え、取得できなければ Actions の実行結果に
    フォールバックする。
    """
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/"

    server = os.environ.get("GITHUB_SERVER_URL")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return None


def send_ntfy(topic: str, *, data: bytes, headers: dict, method: str = "POST") -> int:
    """headers の値は str(ASCIIのみ想定) または bytes(UTF-8などを含む場合は
    呼び出し側で明示的に .encode() したもの)。urllib/http.client は str の
    ヘッダー値を latin-1 でエンコードするため、日本語など非ASCII文字を含む
    値は事前に bytes 化しておく必要がある。
    """
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status


def send_summary(topic: str, latest_date: str, rows: list) -> None:
    msg = build_message(latest_date, rows)
    print(msg)

    tickers_summary = ", ".join(r["ティッカー"] for r in rows)
    headers = {
        "Title": f"Golden Cross: {tickers_summary}"[:250],
        "Tags": "rocket,chart_with_upwards_trend",
        "Priority": "high",
        "Markdown": "yes",
    }
    click_url = build_click_url()
    if click_url:
        headers["Click"] = click_url

    status = send_ntfy(topic, data=msg.encode("utf-8"), headers=headers, method="POST")
    print(f"ntfy.sh summary response: {status}")


def send_attachment(topic: str, csv_path: str, latest_date: str) -> None:
    if not os.path.exists(csv_path):
        return

    caption = f"{latest_date} 時点の全シグナル詳細データです（判定・各条件の合否つき）"
    headers = {
        "Filename": os.path.basename(csv_path),
        "Title": "Signal details (CSV)",
        "Message": caption.encode("utf-8"),
        "Tags": "page_facing_up",
    }
    with open(csv_path, "rb") as f:
        data = f.read()

    status = send_ntfy(topic, data=data, headers=headers, method="PUT")
    print(f"ntfy.sh attachment response: {status}")


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

    send_summary(topic, latest_date, latest)
    send_attachment(topic, SIGNALS_CSV, latest_date)


if __name__ == "__main__":
    sys.exit(main())
