"""
ma_cross_screener.py が出力した CSV から、閲覧しやすい静的HTMLレポートを
生成する（GitHub Pages で公開する想定）。

入力: ma_cross_signals.csv, ma_cross_backtest.csv
出力: _site/index.html
"""

import os
from datetime import datetime, timezone

import pandas as pd

SIGNALS_CSV = "ma_cross_signals.csv"
BACKTEST_CSV = "ma_cross_backtest.csv"
OUT_DIR = "_site"
OUT_FILE = os.path.join(OUT_DIR, "index.html")

CATEGORY_LABEL = {
    "leveraged_bull": "レバレッジ(ブル)",
    "leveraged_inverse": "レバレッジ・インバース",
    "plain_etf": "通常ETF",
    "stock": "個別株",
}


def load_csv(path: str) -> pd.DataFrame | None:
    if not os.path.exists(path):
        return None
    return pd.read_csv(path, encoding="utf-8-sig")


def signal_badge(signal: str) -> str:
    cls = "badge-golden" if signal == "ゴールデンクロス" else "badge-dead"
    return f'<span class="badge {cls}">{signal}</span>'

def verdict_badge(verdict: str) -> str:
    if "高信頼度" in str(verdict):
        cls = "badge-high"
    elif "見送り" in str(verdict):
        cls = "badge-low"
    else:
        cls = "badge-neutral"
    return f'<span class="badge {cls}">{verdict}</span>'


def render_signals_table(df: pd.DataFrame | None) -> str:
    if df is None or df.empty:
        return '<p class="empty">直近5営業日以内に発生したシグナルはありません。</p>'

    df = df.sort_values("発生日", ascending=False)
    rows = []
    for _, r in df.iterrows():
        category = CATEGORY_LABEL.get(r["カテゴリ"], r["カテゴリ"])
        rows.append(
            "<tr>"
            f'<td class="ticker">{r["ティッカー"]}</td>'
            f"<td>{category}</td>"
            f"<td>{signal_badge(r['シグナル'])}</td>"
            f'<td>{r["発生日"]}</td>'
            f'<td class="num">${r["終値"]}</td>'
            f"<td>{verdict_badge(r['判定'])}</td>"
            "</tr>"
        )
    return f"""
<table>
  <thead>
    <tr><th>ティッカー</th><th>カテゴリ</th><th>シグナル</th><th>発生日</th><th>終値</th><th>判定</th></tr>
  </thead>
  <tbody>
    {''.join(rows)}
  </tbody>
</table>
"""


def stat_card(label: str, sub: pd.DataFrame) -> str:
    if sub.empty:
        return ""
    win_rate = (sub["return_pct"] > 0).mean() * 100
    mean = sub["return_pct"].mean()
    median = sub["return_pct"].median()
    n = len(sub)
    return f"""
<div class="card">
  <div class="card-label">{label}</div>
  <div class="card-main">{win_rate:.1f}<span class="unit">% 勝率</span></div>
  <div class="card-sub">平均 {mean:+.2f}% ・ 中央値 {median:+.2f}% ・ n={n}</div>
</div>
"""


def render_backtest_summary(df: pd.DataFrame | None) -> str:
    if df is None or df.empty:
        return '<p class="empty">バックテストデータがありません。</p>'

    golden = df[df["signal"] == "ゴールデンクロス"]
    dead = df[df["signal"] == "デッドクロス"]

    cards = [
        stat_card("ゴールデンクロス（全体）", golden),
        stat_card("デッドクロス（全体）", dead),
    ]

    if "high_confidence(両条件を満たす)" in dead.columns:
        valid = dead[dead["high_confidence(両条件を満たす)"].notna()]
        hi = valid[valid["high_confidence(両条件を満たす)"] == True]  # noqa: E712
        lo = valid[valid["high_confidence(両条件を満たす)"] == False]  # noqa: E712
        cards.append(stat_card("デッドクロス・高信頼度", hi))
        cards.append(stat_card("デッドクロス・低信頼度", lo))

    total_n = len(df)
    n_tickers = df["ticker"].nunique()

    cat_rows = []
    for signal in ["ゴールデンクロス", "デッドクロス"]:
        sub = df[df["signal"] == signal]
        if sub.empty:
            continue
        g = sub.groupby("category")["return_pct"].agg(["count", "mean", "median"])
        win = sub.groupby("category").apply(
            lambda x: (x["return_pct"] > 0).mean() * 100, include_groups=False
        )
        for cat, row in g.iterrows():
            cat_rows.append(
                "<tr>"
                f"<td>{signal_badge(signal)}</td>"
                f"<td>{CATEGORY_LABEL.get(cat, cat)}</td>"
                f'<td class="num">{int(row["count"])}</td>'
                f'<td class="num">{row["mean"]:+.2f}%</td>'
                f'<td class="num">{row["median"]:+.2f}%</td>'
                f'<td class="num">{win.get(cat, float("nan")):.1f}%</td>'
                "</tr>"
            )

    return f"""
<p class="meta">対象クロス件数: {total_n:,}件（{n_tickers}銘柄、クロス後10営業日リターン基準）</p>
<div class="cards">
  {''.join(cards)}
</div>
<table>
  <thead>
    <tr><th>シグナル</th><th>カテゴリ</th><th>件数</th><th>平均</th><th>中央値</th><th>勝率</th></tr>
  </thead>
  <tbody>
    {''.join(cat_rows)}
  </tbody>
</table>
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    signals_df = load_csv(SIGNALS_CSV)
    backtest_df = load_csv(BACKTEST_CSV)

    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MAクロス・スクリーナー</title>
<style>
  :root {{
    --bg: #0f1115;
    --panel: #171a21;
    --border: #262b36;
    --text: #e7e9ee;
    --text-dim: #9aa1b1;
    --accent: #34d399;
    --accent-red: #f87171;
    --accent-amber: #fbbf24;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 24px 16px 64px;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif;
  }}
  .wrap {{ max-width: 920px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 4px; }}
  h2 {{ font-size: 1.1rem; margin: 32px 0 12px; color: var(--text); }}
  .updated {{ color: var(--text-dim); font-size: 0.85rem; margin-bottom: 24px; }}
  .meta {{ color: var(--text-dim); font-size: 0.85rem; }}
  .empty {{ color: var(--text-dim); font-style: italic; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    font-size: 0.9rem;
  }}
  th, td {{
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  th {{ color: var(--text-dim); font-weight: 600; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.03em; }}
  tr:last-child td {{ border-bottom: none; }}
  td.ticker {{ font-weight: 700; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  th:nth-child(3), td:nth-child(3) {{ text-align: right; }}
  th:nth-child(4), td:nth-child(4), th:nth-child(5), td:nth-child(5), th:nth-child(6), td:nth-child(6) {{ text-align: right; }}

  .badge {{
    display: inline-block;
    padding: 3px 9px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
    white-space: nowrap;
  }}
  .badge-golden {{ background: rgba(52,211,153,0.15); color: var(--accent); }}
  .badge-dead {{ background: rgba(248,113,113,0.15); color: var(--accent-red); }}
  .badge-high {{ background: rgba(52,211,153,0.15); color: var(--accent); }}
  .badge-low {{ background: rgba(148,163,184,0.15); color: var(--text-dim); }}
  .badge-neutral {{ background: rgba(251,191,36,0.15); color: var(--accent-amber); }}

  .cards {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
  }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
  }}
  .card-label {{ color: var(--text-dim); font-size: 0.78rem; margin-bottom: 6px; }}
  .card-main {{ font-size: 1.6rem; font-weight: 700; }}
  .card-main .unit {{ font-size: 0.85rem; font-weight: 500; color: var(--text-dim); margin-left: 4px; }}
  .card-sub {{ color: var(--text-dim); font-size: 0.78rem; margin-top: 4px; }}

  .disclaimer {{
    margin-top: 40px;
    padding: 14px 16px;
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text-dim);
    font-size: 0.8rem;
    line-height: 1.6;
  }}
  .scroll {{ overflow-x: auto; }}
  a {{ color: var(--accent); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>📊 MAクロス・スクリーナー</h1>
  <div class="updated">最終更新: {updated_at}（毎日8:00 JST頃に自動更新）</div>

  <h2>直近5営業日のシグナル</h2>
  <div class="scroll">{render_signals_table(signals_df)}</div>

  <h2>バックテスト概要</h2>
  <div class="scroll">{render_backtest_summary(backtest_df)}</div>

  <div class="disclaimer">
    このページは <code>ma_cross_screener.py</code> の実行結果を自動生成したものです。
    表示内容は過去データに基づく統計であり、将来の成績を保証するものではありません。
    投資助言ではなく、投資判断はご自身の責任で行ってください。
    ソース: <a href="https://github.com/{os.environ.get('GITHUB_REPOSITORY', 'koutya1229/ma-cross-screener')}">GitHub</a>
  </div>
</div>
</body>
</html>
"""

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {OUT_FILE}")


if __name__ == "__main__":
    main()
