"""
1458 専用: 日経平均レバレッジ2倍ETFの4種類のトレンドフォロー買いシグナル監視スクリプト

soxl_signal_watch.py と同じロジック・同じ4シグナル定義を、東証上場の1458
(楽天ETF-日経レバレッジ指数連動型)に適用したもの。ma_cross_screener.py の
EMA50/EMA200/RSI(14)/MACD(12,26,9)をそのまま流用する。

シグナル定義:
  1. ゴールデンクロス            : EMA50がEMA200を下から上に抜けた
  2. 200日線奪回                 : 終値がEMA200を下から上に抜けた
  3. RSI売られすぎ離脱           : RSI(14)が30を下から上に抜けた
  4. トレンド中のMACD買いクロス  : EMA50>EMA200（上昇トレンド中）かつ
                                    MACDがシグナル線を下から上に抜けた

いずれも「買い」の参考シグナルのみを扱う。

必要ライブラリ:
    pip install yfinance pandas numpy

使い方:
    python 1458_signal_watch.py

出力:
    1458_signal_watch.csv  直近 RECENT_DAYS 営業日以内に発生したシグナル一覧
                            （該当なしの場合はファイルを生成しない）
"""

from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

from ma_cross_screener import RSI_OVERSOLD, compute_indicators, sanitize_price_series

TICKER = "1458.T"
START_DATE = "2018-01-01"   # EMA200のウォームアップに十分な期間を確保
RECENT_DAYS = 3             # 直近何営業日以内のシグナルを「新規」とみなすか
OUTPUT_CSV = "1458_signal_watch.csv"


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
            if ema50[i - 1] <= ema200[i - 1] and ema50[i] > ema200[i]:
                signals.append((i, "ゴールデンクロス"))

        if not (np.isnan(close[i - 1]) or np.isnan(ema200[i - 1]) or np.isnan(ema200[i])):
            if close[i - 1] <= ema200[i - 1] and close[i] > ema200[i]:
                signals.append((i, "200日線奪回"))

        if not (np.isnan(rsi[i - 1]) or np.isnan(rsi[i])):
            if rsi[i - 1] <= RSI_OVERSOLD and rsi[i] > RSI_OVERSOLD:
                signals.append((i, "RSI売られすぎ離脱"))

        if not (np.isnan(ema50[i]) or np.isnan(ema200[i]) or np.isnan(macd[i - 1])
                or np.isnan(macd[i]) or np.isnan(macd_sig[i - 1]) or np.isnan(macd_sig[i])):
            if ema50[i] > ema200[i] and macd[i - 1] <= macd_sig[i - 1] and macd[i] > macd_sig[i]:
                signals.append((i, "トレンド中のMACD買いクロス"))

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
