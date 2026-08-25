"""
ma_cross_screener.py が出力した CSV から、閲覧しやすい静的HTMLレポートを
生成する（GitHub Pages で公開する想定）。

入力: ma_cross_signals.csv, ma_cross_backtest.csv
出力: _site/index.html
"""

import base64
import json
import os
from datetime import datetime, timezone
from io import BytesIO

import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SIGNALS_CSV = "ma_cross_signals.csv"
BACKTEST_CSV = "ma_cross_backtest.csv"
APPROACHING_CSV = "ma_cross_approaching.csv"
CHART_DATA_CSV = "ma_cross_chart_data.csv"
TRACK_RECORD_FILE = "signal_track_record.json"
OUT_DIR = "_site"
OUT_FILE = os.path.join(OUT_DIR, "index.html")

CHART_COLORS = {
    "close": "#9aa1b1",
    "ema10": "#34d399",
    "ema20": "#f87171",
    "cross": "#fbbf24",
    "grid": "#262b36",
    "text": "#9aa1b1",
}

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
        action = r["推奨アクション"] if "推奨アクション" in df.columns and pd.notna(r.get("推奨アクション")) else "-"
        rows.append(
            "<tr>"
            f'<td class="ticker">{r["ティッカー"]}</td>'
            f"<td>{category}</td>"
            f"<td>{signal_badge(r['シグナル'])}</td>"
            f'<td>{r["発生日"]}</td>'
            f'<td class="num">${r["終値"]}</td>'
            f"<td>{verdict_badge(r['判定'])}</td>"
            f'<td class="action">{action}</td>'
            "</tr>"
        )
    return f"""
<table>
  <thead>
    <tr><th>ティッカー</th><th>カテゴリ</th><th>シグナル</th><th>発生日</th><th>終値</th><th>判定</th><th>推奨アクション</th></tr>
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


def render_chart(ticker_df: pd.DataFrame, cross_date: str) -> str:
    """1銘柄分のEMAチャートをPNG(base64)として描画する。"""
    fig, ax = plt.subplots(figsize=(6, 2.3), dpi=140)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")

    ax.plot(ticker_df["Date"], ticker_df["Close"], color=CHART_COLORS["close"], linewidth=1, label="Close")
    ax.plot(ticker_df["Date"], ticker_df["EMA10"], color=CHART_COLORS["ema10"], linewidth=1.4, label="EMA10")
    ax.plot(ticker_df["Date"], ticker_df["EMA20"], color=CHART_COLORS["ema20"], linewidth=1.4, label="EMA20")

    match = ticker_df[ticker_df["Date"] == cross_date]
    if not match.empty:
        ax.scatter(match["Date"], match["Close"], color=CHART_COLORS["cross"], s=45, zorder=5, label="Cross")

    n_ticks = min(6, len(ticker_df))
    tick_idx = list(range(0, len(ticker_df), max(1, len(ticker_df) // n_ticks)))
    ax.set_xticks([ticker_df["Date"].iloc[i] for i in tick_idx])
    ax.tick_params(colors=CHART_COLORS["text"], labelsize=6.5)
    ax.tick_params(axis="x", rotation=30)
    for spine in ax.spines.values():
        spine.set_color(CHART_COLORS["grid"])
    ax.grid(axis="y", color=CHART_COLORS["grid"], linewidth=0.5, alpha=0.6)
    ax.legend(loc="upper left", fontsize=6.5, frameon=False, labelcolor=CHART_COLORS["text"])
    fig.tight_layout(pad=0.6)

    buf = BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def render_charts_section(chart_df: pd.DataFrame | None, signals_df: pd.DataFrame | None) -> str:
    if chart_df is None or chart_df.empty or signals_df is None or signals_df.empty:
        return '<p class="empty">チャート表示対象のデータがありません。</p>'

    # 銘柄ごとに最新の発生日をクロス表示位置として使う
    latest_signal_date = (
        signals_df.sort_values("発生日").groupby("ティッカー")["発生日"].last().to_dict()
    )

    cards = []
    for ticker in chart_df["ティッカー"].unique():
        sub = chart_df[chart_df["ティッカー"] == ticker].sort_values("Date")
        if sub.empty:
            continue
        cross_date = latest_signal_date.get(ticker, "")
        img_b64 = render_chart(sub, cross_date)
        cards.append(f"""
<div class="chart-card">
  <div class="chart-title">{ticker}</div>
  <img src="data:image/png;base64,{img_b64}" alt="{ticker} EMA chart" loading="lazy">
</div>
""")

    return f'<div class="chart-grid">{"".join(cards)}</div>'


def render_approaching(df: pd.DataFrame | None) -> str:
    if df is None or df.empty:
        return '<p class="empty">現在、接近中のクロスはありません。</p>'

    df = df.sort_values("乖離率(%)")
    rows = []
    for _, r in df.iterrows():
        category = CATEGORY_LABEL.get(r["カテゴリ"], r["カテゴリ"])
        rows.append(
            "<tr>"
            f'<td class="ticker">{r["ティッカー"]}</td>'
            f"<td>{category}</td>"
            f"<td>{signal_badge(r['接近中のシグナル'])}</td>"
            f'<td class="num">{r["乖離率(%)"]}%</td>'
            f'<td class="num">${r["終値"]}</td>'
            "</tr>"
        )
    return f"""
<table>
  <thead>
    <tr><th>ティッカー</th><th>カテゴリ</th><th>接近中のシグナル</th><th>乖離率</th><th>終値</th></tr>
  </thead>
  <tbody>
    {''.join(rows)}
  </tbody>
</table>
"""


def load_track_record() -> list:
    if not os.path.exists(TRACK_RECORD_FILE):
        return []
    try:
        with open(TRACK_RECORD_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def render_track_record(records: list) -> str:
    if not records:
        return '<p class="empty">まだ記録がありません（アクション対象シグナルが発生すると自動で記録が始まります）。</p>'

    resolved = [r for r in records if r.get("resolved")]
    pending = [r for r in records if not r.get("resolved")]

    parts = []
    if resolved:
        recent = resolved[-20:]
        win_rate = sum(1 for r in recent if r["return_pct"] > 0) / len(recent) * 100
        mean = sum(r["return_pct"] for r in recent) / len(recent)
        parts.append(f"""
<div class="cards">
<div class="card">
  <div class="card-label">実運用シグナルの実績（直近{len(recent)}件）</div>
  <div class="card-main">{win_rate:.1f}<span class="unit">% 勝率</span></div>
  <div class="card-sub">平均リターン {mean:+.2f}% ・ 累計記録{len(records)}件（うち確定{len(resolved)}件）</div>
</div>
</div>
""")
        rows = []
        for r in reversed(recent):
            win = r["return_pct"] > 0
            cls = "badge-golden" if win else "badge-dead"
            label = "的中" if win else "外れ"
            rows.append(
                "<tr>"
                f'<td class="ticker">{r["ticker"]}</td>'
                f"<td>{signal_badge(r['signal'])}</td>"
                f'<td>{r["entry_date"]} → {r["exit_date"]}</td>'
                f'<td class="num">{r["return_pct"]:+.2f}%</td>'
                f'<td><span class="badge {cls}">{label}</span></td>'
                "</tr>"
            )
        parts.append(f"""
<table>
  <thead>
    <tr><th>ティッカー</th><th>シグナル</th><th>期間</th><th>リターン</th><th>結果</th></tr>
  </thead>
  <tbody>
    {''.join(rows)}
  </tbody>
</table>
""")

    if pending:
        parts.append(f'<p class="meta" style="margin-top:12px">結果確定待ち: {len(pending)}件（発生から10営業日経過後に確定します）</p>')

    return "".join(parts)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    signals_df = load_csv(SIGNALS_CSV)
    backtest_df = load_csv(BACKTEST_CSV)
    approaching_df = load_csv(APPROACHING_CSV)
    chart_df = load_csv(CHART_DATA_CSV)
    track_records = load_track_record()

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
  td.action {{ white-space: normal; min-width: 260px; color: var(--text-dim); font-size: 0.85rem; line-height: 1.5; }}
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

  .chart-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 12px;
  }}
  .chart-card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 12px 4px;
  }}
  .chart-title {{ font-weight: 700; font-size: 0.85rem; margin-bottom: 2px; }}
  .chart-card img {{ width: 100%; height: auto; display: block; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>📊 MAクロス・スクリーナー</h1>
  <div class="updated">最終更新: {updated_at}（毎日8:00 JST頃に自動更新）</div>

  <h2>直近5営業日のシグナル</h2>
  <div class="scroll">{render_signals_table(signals_df)}</div>

  <h2>📈 EMAチャート</h2>
  {render_charts_section(chart_df, signals_df)}

  <h2>⚠️ クロス接近中（早期警告）</h2>
  <div class="scroll">{render_approaching(approaching_df)}</div>

  <h2>✅ シグナルの実運用実績</h2>
  <div class="scroll">{render_track_record(track_records)}</div>

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
