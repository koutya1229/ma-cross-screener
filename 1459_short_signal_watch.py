"""
1459 専用: 日経ダブルインバースETFの4種類のトレンドフォロー「空売り(ショート)」
シグナル監視スクリプト

1459(楽天ETF-日経ダブルインバース指数連動型)を対象に、買いシグナルの
鏡写しとなる「売り(ショートエントリー)」シグナルのみを監視する。
2026年9月のチャットでの検証で、1459は構造的な下降トレンドが続いており、
買い(ロング)のトレンドフォローシグナルはほぼ機能しなかった一方、
同じロジックを売り方向に反転させたシグナルは良好な成績だったことを
踏まえたもの。

ma_cross_screener.py の EMA50/EMA200/RSI(14)/MACD(12,26,9)を流用する。

シグナル定義（すべて「売り(ショートエントリー)」の参考シグナル）:
  1. デッドクロス                : EMA50がEMA200を上から下に抜けた
  2. 200日線割れ                 : 終値がEMA200を上から下に抜けた
  3. RSI買われすぎ反落           : RSI(14)が70を上から下に抜けた
  4. トレンド中のMACD売りクロス  : EMA50<EMA200（下降トレンド中）かつ
                                    MACDがシグナル線を上から下に抜けた

注意: これは信用取引(空売り)のシグナルであり、現物買いより損失リスクが
大きい(理論上無限大)。貸株料・逆日歩・追証リスクも考慮していない、
価格変動のみに基づく機械的な判定である点に留意すること。

必要ライブラリ:
    pip install yfinance pandas numpy

使い方:
    python 1459_short_signal_watch.py

出力:
    1459_short_signal_watch.csv  直近 RECENT_DAYS 営業日以内に発生した
                                  シグナル一覧（該当なしの場合はファイルを
                                  生成しない）
"""

from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

from ma_cross_screener import RSI_OVERBOUGHT, compute_indicators, sanitize_price_series

TICKER = "1459.T"
START_DATE = "2018-01-01"   # EMA200のウォームアップに十分な期間を確保
RECENT_DAYS = 3             # 直近何営業日以内のシグナルを「新規」とみなすか
OUTPUT_CSV = "1459_short_signal_watch.csv"


def find_signals(df: pd.DataFrame) -> list[tuple[int, str]]:
    ema50 = df["EMA50"].to_numpy(dtype=float)
    ema200 = df["EMA200"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    rsi = df["RSI"].to_numpy(dtype=float)
    macd = df["MACD"].to_numpy(dtype=float)
    macd_sig = df["MACD_SIGNAL"].to_numpy(dtype=float)

    signals: list[tuple[int, str]] = []
    for i in range(1, len(df)):
        if not (np.isnan(ema50[i - 1]) or np.isnan(ema50[i]) or np.isnan(ema200[i - 1]) or np.isnan(ema200[i])):
            if ema50[i - 1] >= ema200[i - 1] and ema50[i] < ema200[i]:
                signals.append((i, "デッドクロス"))

        if not (np.isnan(close[i - 1]) or np.isnan(ema200[i - 1]) or np.isnan(ema200[i])):
            if close[i - 1] >= ema200[i - 1] and close[i] < ema200[i]:
                signals.append((i, "200日線割れ"))

        if not (np.isnan(rsi[i - 1]) or np.isnan(rsi[i])):
            if rsi[i - 1] >= RSI_OVERBOUGHT and rsi[i] < RSI_OVERBOUGHT:
                signals.append((i, "RSI買われすぎ反落"))

        if not (np.isnan(ema50[i]) or np.isnan(ema200[i]) or np.isnan(macd[i - 1])
                or np.isnan(macd[i]) or np.isnan(macd_sig[i - 1]) or np.isnan(macd_sig[i])):
            if ema50[i] < ema200[i] and macd[i - 1] >= macd_sig[i - 1] and macd[i] < macd_sig[i]:
                signals.append((i, "トレンド中のMACD売りクロス"))

    return signals


def main() -> None:
    end = datetime.today()
    start = datetime.strptime(START_DATE, "%Y-%m-%d")

    df = yf.download(TICKER, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        print(f"{TICKER}: データ取得失敗")
        return
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = sanitize_price_series(df, TICKER)
    df = compute_indicators(df)

    signals = find_signals(df)
    cutoff_idx = len(df) - 1 - RECENT_DAYS
    recent = [(i, s) for i, s in signals if i >= cutoff_idx]

    if not recent:
        print(f"{TICKER}: 直近{RECENT_DAYS}営業日以内の新規シグナルなし（4種とも）")
        return

    rows = []
    for i, sig in recent:
        row = df.iloc[i]
        rows.append({
            "ティッカー": TICKER,
            "シグナル": sig,
            "発生日": row.name.strftime("%Y-%m-%d"),
            "終値": round(float(row["Close"]), 1),
            "RSI": round(float(row["RSI"]), 1),
        })
        print(f"[{sig}] {TICKER} ({row.name.date()}, 終値{row['Close']:.1f}, RSI{row['RSI']:.1f})")

    pd.DataFrame(rows).to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n結果を {OUTPUT_CSV} に保存しました。")


if __name__ == "__main__":
    main()
