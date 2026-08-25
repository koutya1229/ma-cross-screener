"""
10日EMA / 20日EMA ゴールデンクロス・デッドクロス スクリーナー
  + 個別条件ベースの精度検証（合計スコアではなく、各条件単体の効果を検証）
  + 商品タイプ別（通常ETF/株 vs レバレッジ/インバース）の分析
  + 下落相場（2018年Q4, 2020年コロナショック, 2022年弱気相場）を含む
    長期データでのバックテスト機能
  + 推奨アクション（資金配分シミュレーション、実勢為替レート反映）
  + クロス接近の早期警告
  + シグナルの実運用成績トラッキング（signal_track_record.json に永続化）
  + レポート用チャートデータ出力

必要ライブラリ:
    pip install yfinance pandas numpy

使い方:
    python ma_cross_screener.py

出力:
    ma_cross_signals.csv      直近シグナル一覧（各条件の合否・推奨アクションつき）
    ma_cross_backtest.csv     過去の全クロスと、各条件の合否・N日後リターン
                              （このCSVを使えば「どの条件が本当に効くか」を後から検証可能）
    ma_cross_approaching.csv  まだクロスしていないが接近中の銘柄
    ma_cross_chart_data.csv   直近シグナルが出た銘柄のEMAチャート用データ
    signal_track_record.json 実運用シグナルの成績記録（累積・要コミット）
"""

import json
import os

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ------------------------------------------------------------
# 設定項目
# ------------------------------------------------------------

TICKERS = [
    # --- 米国 ---
    "SOXL", "SOXS", "SOXX", "SMH",
    "TQQQ", "SQQQ", "QQQ",
    "SPY", "SPXL",
    "NVDA", "AMD", "TSM",
    # --- 日本（東証、yfinanceは "XXXX.T" 形式） ---
    "1321.T", "1306.T",   # 日経225連動型上場投信 / TOPIX連動型上場投信
    "1570.T", "1357.T",   # 日経平均レバレッジ / 日経平均ダブルインバース
    "7203.T", "6758.T", "7974.T", "8035.T", "9984.T",  # トヨタ・ソニーG・任天堂・東京エレクトロン・ソフトバンクG
    "8306.T", "9432.T", "6501.T", "8058.T", "9983.T",  # 三菱UFJ・NTT・日立・三菱商事・ファーストリテイリング
    "6861.T", "4063.T", "7267.T", "6098.T", "4568.T",  # キーエンス・信越化学・ホンダ・リクルートHD・第一三共
]

# 商品タイプの分類（レバレッジ・インバース商品は値動きの性質が異なるため区別する）
TICKER_CATEGORY = {
    "SOXL": "leveraged_bull", "TQQQ": "leveraged_bull", "SPXL": "leveraged_bull",
    "SOXS": "leveraged_inverse", "SQQQ": "leveraged_inverse",
    "SOXX": "plain_etf", "SMH": "plain_etf", "QQQ": "plain_etf", "SPY": "plain_etf",
    "NVDA": "stock", "AMD": "stock", "TSM": "stock",
    "1570.T": "leveraged_bull",
    "1357.T": "leveraged_inverse",
    "1321.T": "plain_etf", "1306.T": "plain_etf",
    "7203.T": "stock", "6758.T": "stock", "7974.T": "stock", "8035.T": "stock", "9984.T": "stock",
    "8306.T": "stock", "9432.T": "stock", "6501.T": "stock", "8058.T": "stock", "9983.T": "stock",
    "6861.T": "stock", "4063.T": "stock", "7267.T": "stock", "6098.T": "stock", "4568.T": "stock",
}

SHORT_WINDOW = 10
LONG_WINDOW = 20
TREND_WINDOW_1 = 50
TREND_WINDOW_2 = 200
RSI_WINDOW = 14
ATR_WINDOW = 14
VOL_MA_WINDOW = 20
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9

RECENT_CROSS_DAYS = 5

# --- 資金配分シミュレーション（推奨アクションの参考情報として表示） ---
TOTAL_CAPITAL_JPY = 1_000_000   # 前提となる総運用資金（円）
RISK_PCT_PER_TRADE = 0.01       # 1トレードで許容するリスク（総資金に対する割合）
MAX_POSITION_PCT = 0.25         # 1銘柄への投資上限（総資金に対する割合）
USD_JPY_FALLBACK_RATE = 150.0   # 実勢レートが取得できない場合に使う固定フォールバック値
JP_STOCK_LOT_SIZE = 100         # 日本の個別株の単元株数（ETFは1口単位として扱う）

# 楽天証券の米国株式信用取引は「レバレッジ型・インバース型でないこと」が
# 対象条件のため、この5銘柄は空売り不可（現物保有分の売却のみ可能）。
# 他の証券会社・条件では扱いが異なる場合があるため、必要に応じて調整すること。
MARGIN_SHORT_INELIGIBLE = {"SOXL", "SOXS", "TQQQ", "SQQQ", "SPXL"}

# --- クロス接近の早期警告 ---
NEAR_CROSS_THRESHOLD_PCT = 0.5  # EMA10/EMA20の乖離率がこれ未満なら「接近中」とみなす

# --- チャート表示用データ ---
CHART_LOOKBACK_DAYS = 90        # レポートに表示するチャートの表示期間
CHART_DATA_FILE = "ma_cross_chart_data.csv"

# --- シグナルの成績追跡（GitHub Actions側でコミットして永続化する） ---
TRACK_RECORD_FILE = "signal_track_record.json"
TRACK_RECORD_MAX_KEEP = 200     # 肥大化防止のため保持する最大件数（古いものから削除）

# バックテスト開始日
# 2018年Q4急落・2020年コロナショック・2022年弱気相場を含むよう、
# 過去分をさかのぼって取得する（前回は2024年10月以降＝ほぼ上昇相場のみだった）
BACKTEST_START_DATE = "2015-01-01"

BACKTEST_FORWARD_DAYS = 10
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# 主要な下落局面（この期間に発生したクロスを別集計するためのラベル）
BEAR_PERIODS = [
    ("2018年Q4急落", "2018-10-01", "2018-12-31"),
    ("2020年コロナショック", "2020-02-15", "2020-04-15"),
    ("2022年弱気相場", "2022-01-01", "2022-10-31"),
]


def label_market_regime(date) -> str:
    for label, start_s, end_s in BEAR_PERIODS:
        if pd.Timestamp(start_s) <= date <= pd.Timestamp(end_s):
            return label
    return "通常/上昇局面"


# 1日でこの倍率を超える値動きは、株式併合（リバーススプリット）や配信元の
# 一時的なデータ異常とみなす（レバレッジETFの実際の急騰急落でも観測される
# 最大変動幅は概ね±40〜55%程度のため、十分な余裕を持たせた閾値にしている）
SPLIT_JUMP_UP = 2.5
SPLIT_JUMP_DOWN = 0.4


def sanitize_price_series(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """終値の1日ジャンプを検出し、その時点より過去の価格を比率で遡及調整する

    低出来高の銘柄や一部の海外ETF・日本のレバレッジ/インバースETFでは、
    株式併合やデータ配信側の不具合により、yfinanceのauto_adjust処理後も
    終値が1日で数十〜数千倍に跳ねる/戻ることがある。放置するとEMAクロス
    やリターン計算が破綻するため、通常の株式分割調整と同じ方法（発生日
    より前の価格に比率を掛けて連続させる）で補正する。
    """
    close = df["Close"].to_numpy(dtype=float)
    if len(close) < 2:
        return df

    ratio = np.ones(len(close))
    ratio[1:] = close[1:] / close[:-1]
    jump_idx = np.where(
        (ratio > SPLIT_JUMP_UP) | ((ratio < SPLIT_JUMP_DOWN) & (ratio > 0))
    )[0]
    if len(jump_idx) == 0:
        return df

    df = df.copy()
    for i in jump_idx:
        factor = ratio[i]
        print(f"  [{ticker}] {df.index[i].date()} に価格の不連続を検出（前日比{factor:.3f}倍）"
              f"→ それ以前の価格を遡及調整します")
        for col in ["Open", "High", "Low", "Close"]:
            df.iloc[:i, df.columns.get_loc(col)] *= factor

    return df

# ------------------------------------------------------------
# 指標計算
# ------------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["EMA10"] = df["Close"].ewm(span=SHORT_WINDOW, adjust=False).mean()
    df["EMA20"] = df["Close"].ewm(span=LONG_WINDOW, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=TREND_WINDOW_1, adjust=False).mean()
    df["EMA200"] = df["Close"].ewm(span=TREND_WINDOW_2, adjust=False).mean()

    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / RSI_WINDOW, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_WINDOW, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))
    df["RSI"] = df["RSI"].fillna(50)

    ema_fast = df["Close"].ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=MACD_SLOW, adjust=False).mean()
    df["MACD"] = ema_fast - ema_slow
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=MACD_SIGNAL, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIGNAL"]

    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1 / ATR_WINDOW, adjust=False).mean()
    df["ATR_PCT"] = df["ATR"] / df["Close"] * 100

    df["VOL_MA"] = df["Volume"].rolling(VOL_MA_WINDOW).mean()

    df["diff"] = df["EMA10"] - df["EMA20"]

    return df


def find_all_crosses(df: pd.DataFrame):
    crosses = []
    diff = df["diff"].values
    for i in range(1, len(diff)):
        if np.isnan(diff[i - 1]) or np.isnan(diff[i]):
            continue
        if diff[i - 1] < 0 and diff[i] > 0:
            crosses.append((i, "ゴールデンクロス"))
        elif diff[i - 1] > 0 and diff[i] < 0:
            crosses.append((i, "デッドクロス"))
    return crosses


def evaluate_conditions(row: pd.Series, signal: str) -> dict:
    """統計検証で有効性が確認された条件のみを判定する

    検証結果（2015-01〜、下落局面3回を含む1,401件のクロスで検証）:
      - デッドクロス: EMA50<EMA200（下降トレンド確立）で勝率65.4% vs 40.4%
                      (z=5.78, p<0.0001 で有意)
      - デッドクロス: 出来高が20日平均を下回る場合の方が勝率55.4% vs 41.7%
                      (z=-3.54, p=0.0004 で有意)
      - ゴールデンクロス: 検証した5条件はいずれも有意差なし
                          （素のシグナルのままで勝率57.4%、フィルター不要）

    このため、ゴールデンクロスは無条件のシグナルとして扱い、
    デッドクロスのみ「高信頼度」フラグ（2条件のAND）を付与する。
    """
    if signal == "ゴールデンクロス":
        return {}

    # デッドクロス: 統計的に有意だった2条件のみ
    downtrend_confirmed = bool(row["EMA50"] < row["EMA200"])
    volume_not_spiking = (
        bool(row["Volume"] < row["VOL_MA"]) if not np.isnan(row["VOL_MA"]) else None
    )
    high_confidence = bool(
        downtrend_confirmed and (volume_not_spiking is True)
    )

    return {
        "cond_downtrend_confirmed(EMA50<EMA200)": downtrend_confirmed,
        "cond_volume_not_spiking(出来高が平均未満)": volume_not_spiking,
        "high_confidence(両条件を満たす)": high_confidence,
    }


def is_jp_ticker(ticker: str) -> bool:
    return ticker.endswith(".T")


def lot_size(ticker: str, category: str) -> int:
    # 日本の個別株のみ単元株（100株）単位。ETF・米国株は1単位として扱う。
    if is_jp_ticker(ticker) and category == "stock":
        return JP_STOCK_LOT_SIZE
    return 1


def fetch_usd_jpy_rate() -> float:
    """ドル円の実勢レートを取得する。取得できない場合は固定フォールバック値を返す。"""
    try:
        fx_df = yf.download("JPY=X", period="5d", progress=False, auto_adjust=True)
        if isinstance(fx_df.columns, pd.MultiIndex):
            fx_df.columns = fx_df.columns.get_level_values(0)
        rate = float(fx_df["Close"].dropna().iloc[-1])
        if 50 < rate < 500:
            return rate
    except Exception as e:
        print(f"為替レート取得失敗（固定値{USD_JPY_FALLBACK_RATE}円にフォールバック）: {e}")
    return USD_JPY_FALLBACK_RATE


def position_sizing(ticker: str, category: str, price: float, stop_pct: float, fx_rate: float) -> str:
    """総資金 TOTAL_CAPITAL_JPY を前提に、1トレードあたりのリスク許容額
    （RISK_PCT_PER_TRADE）と撤退目安（stop_pct）から、具体的な株数・投資額
    を逆算する。

    計算式: 購入株数 ≒ リスク許容額 ÷ (価格 × 撤退%)
    1銘柄への投資額は MAX_POSITION_PCT を超えないようキャップする。
    """
    if price is None or np.isnan(price) or not stop_pct:
        return ""

    jp = is_jp_ticker(ticker)
    currency = "¥" if jp else "$"
    fx = 1.0 if jp else fx_rate

    risk_amount = TOTAL_CAPITAL_JPY * RISK_PCT_PER_TRADE / fx
    loss_per_unit = price * stop_pct / 100
    if loss_per_unit <= 0:
        return ""

    lot = lot_size(ticker, category)
    shares = max(lot, int((risk_amount / loss_per_unit) // lot) * lot)

    cap_amount = TOTAL_CAPITAL_JPY * MAX_POSITION_PCT / fx
    while shares > lot and shares * price > cap_amount:
        shares -= lot

    investment = shares * price
    capital_native = TOTAL_CAPITAL_JPY / fx
    pct_of_capital = investment / capital_native * 100
    amount_str = f"{currency}{investment:,.0f}" if jp else f"{currency}{investment:,.1f}"

    warning = ""
    if pct_of_capital > MAX_POSITION_PCT * 100:
        warning = "（単元株の制約で上限超過、資金配分に注意）"

    return f"【{TOTAL_CAPITAL_JPY // 10000}万円運用の目安】{shares}株・{amount_str}（資金の{pct_of_capital:.1f}%）{warning}"


def suggest_action(
    ticker: str, signal: str, category: str, high_confidence, atr_pct: float, price: float, fx_rate: float
) -> str:
    """判定結果に応じた具体的な売買アクションの目安を提示する。

    ATR%（過去14日の平均的な値動き幅）の2倍を、翌営業日以降の撤退（損切り）
    目安として使う（一般的なボラティリティ連動ストップの考え方）。
    バックテストの傾向（[[category]]別の勝率・標準偏差）を踏まえた参考情報
    であり、投資助言ではない。
    """
    stop_pct = None
    if atr_pct is not None and not np.isnan(atr_pct):
        stop_pct = round(atr_pct * 2, 1)
    stop_note = f"翌営業日以降、終値がエントリー比-{stop_pct}%を下回ったら撤退目安" if stop_pct else ""
    sizing_note = position_sizing(ticker, category, price, stop_pct, fx_rate) if stop_pct else ""

    if signal == "ゴールデンクロス":
        if category == "leveraged_inverse":
            return "統計的に不利（過去勝率37%程度）。見送り推奨"
        action = "翌営業日の始値付近で買い、10営業日後を目安に手仕舞い"
        if category == "leveraged_bull":
            action += "。値動きが大きいため通常より小さめの数量で"
        parts = [p for p in [action, stop_note, sizing_note] if p]
        return "。".join(parts)

    # デッドクロス
    if high_confidence:
        if ticker in MARGIN_SHORT_INELIGIBLE:
            return "空売り不可（レバレッジ/インバース型は米国株信用取引の対象外）。現物保有していれば売却を検討、新規の売りポジションは持てません"
        base = "空売り、または保有株の利確・損切りを検討。10営業日後を目安に手仕舞い"
        parts = [p for p in [base, stop_note, sizing_note] if p]
        return "。".join(parts)
    return "見送り推奨。ノーアクションが無難"


# ------------------------------------------------------------
# 現在のシグナル表示
# ------------------------------------------------------------

def get_recent_signals(ticker: str, df: pd.DataFrame, fx_rate: float):
    crosses = find_all_crosses(df)
    cutoff_idx = len(df) - 1 - RECENT_CROSS_DAYS
    recent = [c for c in crosses if c[0] >= cutoff_idx]

    results = []
    for idx, signal in recent:
        row = df.iloc[idx]
        conditions = evaluate_conditions(row, signal)
        if signal == "ゴールデンクロス":
            note = "フィルター不要（素のシグナルで勝率57.4%）"
        else:
            note = "高信頼度" if conditions.get("high_confidence(両条件を満たす)") else "低信頼度（見送り推奨）"
        category = TICKER_CATEGORY.get(ticker, "unknown")
        action = suggest_action(
            ticker, signal, category, conditions.get("high_confidence(両条件を満たす)"),
            row.get("ATR_PCT"), float(row["Close"]), fx_rate,
        )
        results.append({
            "ティッカー": ticker,
            "カテゴリ": category,
            "シグナル": signal,
            "発生日": row.name.strftime("%Y-%m-%d"),
            "終値": round(float(row["Close"]), 2),
            "判定": note,
            "推奨アクション": action,
            **conditions,
        })
    return results


def get_approaching_crosses(ticker: str, df: pd.DataFrame):
    """まだクロスしていないが、EMA10とEMA20が接近している銘柄を検出する
    （NEAR_CROSS_THRESHOLD_PCT 未満の乖離率を「接近中」とみなす早期警告）。
    直近 RECENT_CROSS_DAYS 以内に既にクロスが発生している銘柄は対象外。
    """
    crosses = find_all_crosses(df)
    cutoff_idx = len(df) - 1 - RECENT_CROSS_DAYS
    if any(idx >= cutoff_idx for idx, _ in crosses):
        return []

    latest = df.iloc[-1]
    ema10, ema20 = latest["EMA10"], latest["EMA20"]
    if np.isnan(ema10) or np.isnan(ema20) or ema20 == 0:
        return []

    diff_pct = abs(ema10 - ema20) / abs(ema20) * 100
    if diff_pct > NEAR_CROSS_THRESHOLD_PCT:
        return []

    direction = "ゴールデンクロス" if ema10 < ema20 else "デッドクロス"
    return [{
        "ティッカー": ticker,
        "カテゴリ": TICKER_CATEGORY.get(ticker, "unknown"),
        "接近中のシグナル": direction,
        "乖離率(%)": round(float(diff_pct), 2),
        "終値": round(float(latest["Close"]), 2),
        "日付": latest.name.strftime("%Y-%m-%d"),
    }]


# ------------------------------------------------------------
# バックテスト
# ------------------------------------------------------------

def backtest_ticker(ticker: str, df: pd.DataFrame):
    crosses = find_all_crosses(df)
    records = []
    close = df["Close"].values

    for idx, signal in crosses:
        if idx + BACKTEST_FORWARD_DAYS >= len(df):
            continue
        row = df.iloc[idx]
        conditions = evaluate_conditions(row, signal)

        entry_price = close[idx]
        exit_price = close[idx + BACKTEST_FORWARD_DAYS]
        ret_pct = (exit_price / entry_price - 1) * 100
        if signal == "デッドクロス":
            ret_pct = -ret_pct

        records.append({
            "ticker": ticker,
            "category": TICKER_CATEGORY.get(ticker, "unknown"),
            "signal": signal,
            "date": row.name.strftime("%Y-%m-%d"),
            "regime": label_market_regime(row.name),
            "return_pct": ret_pct,
            **conditions,
        })

    return records


# ------------------------------------------------------------
# シグナルの成績追跡（実運用でのシグナルを記録し、後日結果を確定する）
# ------------------------------------------------------------

def load_track_record() -> list:
    if os.path.exists(TRACK_RECORD_FILE):
        try:
            with open(TRACK_RECORD_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_track_record(records: list) -> None:
    # 直近分のみ保持（先頭＝古い順に格納しているため、末尾側を残す）
    trimmed = records[-TRACK_RECORD_MAX_KEEP:]
    with open(TRACK_RECORD_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def update_track_record(records: list, ticker: str, df: pd.DataFrame) -> list:
    """(1) 最新バーがアクション対象シグナル（ゴールデンクロス or 高信頼度
    デッドクロス）なら新規記録を追加し、(2) 既存の未確定記録のうち
    BACKTEST_FORWARD_DAYS 営業日が経過したものの結果を確定する。
    """
    last_idx = len(df) - 1
    crosses = find_all_crosses(df)

    if crosses and crosses[-1][0] == last_idx:
        idx, signal = crosses[-1]
        row = df.iloc[idx]
        conditions = evaluate_conditions(row, signal)
        is_actionable = signal == "ゴールデンクロス" or bool(conditions.get("high_confidence(両条件を満たす)"))
        if is_actionable:
            entry_date = row.name.strftime("%Y-%m-%d")
            already_logged = any(
                r["ticker"] == ticker and r["entry_date"] == entry_date for r in records
            )
            if not already_logged:
                records.append({
                    "ticker": ticker,
                    "category": TICKER_CATEGORY.get(ticker, "unknown"),
                    "signal": signal,
                    "entry_date": entry_date,
                    "entry_price": round(float(row["Close"]), 4),
                    "resolved": False,
                    "exit_date": None,
                    "return_pct": None,
                })

    date_index = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}
    close = df["Close"].values
    for r in records:
        if r["resolved"] or r["ticker"] != ticker:
            continue
        entry_idx = date_index.get(r["entry_date"])
        if entry_idx is None:
            continue
        exit_idx = entry_idx + BACKTEST_FORWARD_DAYS
        if exit_idx >= len(df):
            continue
        ret = (close[exit_idx] / r["entry_price"] - 1) * 100
        if r["signal"] == "デッドクロス":
            ret = -ret
        r["resolved"] = True
        r["exit_date"] = df.index[exit_idx].strftime("%Y-%m-%d")
        r["return_pct"] = round(float(ret), 2)

    return records


def summarize_backtest(all_records: list):
    if not all_records:
        print("バックテスト対象のクロスが見つかりませんでした。")
        return

    bt_df = pd.DataFrame(all_records)
    cond_cols = [c for c in bt_df.columns if c.startswith("cond_")]

    print(f"\n{'=' * 70}")
    print(f"バックテスト結果（クロス後{BACKTEST_FORWARD_DAYS}営業日のリターン）")
    print(f"対象クロス件数: {len(bt_df)}件（{bt_df['ticker'].nunique()}銘柄）")
    print(f"{'=' * 70}")

    # --- 全体（外れ値の影響を見るため mean と median 両方） ---
    for signal in ["ゴールデンクロス", "デッドクロス"]:
        sub = bt_df[bt_df["signal"] == signal]
        if sub.empty:
            continue
        risk_adj = sub["return_pct"].mean() / sub["return_pct"].std() if sub["return_pct"].std() else float("nan")
        print(f"\n■ {signal}  全体 n={len(sub)}")
        print(f"  平均={sub['return_pct'].mean():.2f}%  中央値={sub['return_pct'].median():.2f}%  "
              f"勝率={(sub['return_pct'] > 0).mean() * 100:.1f}%  標準偏差={sub['return_pct'].std():.2f}  "
              f"リスク調整後={risk_adj:.2f}")

    # --- デッドクロスの絞り込み効果（high_confidence フラグの有無で比較） ---
    print(f"\n{'-' * 70}")
    print("デッドクロス絞り込みの効果（高信頼度フラグ：EMA50<EMA200 かつ 出来高<平均）")
    print(f"{'-' * 70}")
    dc = bt_df[bt_df["signal"] == "デッドクロス"]
    if not dc.empty and "high_confidence(両条件を満たす)" in dc.columns:
        valid = dc[dc["high_confidence(両条件を満たす)"].notna()]
        hi = valid[valid["high_confidence(両条件を満たす)"] == True]
        lo = valid[valid["high_confidence(両条件を満たす)"] == False]
        if not hi.empty:
            print(f"  高信頼度(n={len(hi)}): 平均={hi['return_pct'].mean():.2f}% "
                  f"中央値={hi['return_pct'].median():.2f}% 勝率={(hi['return_pct']>0).mean()*100:.1f}% "
                  f"標準偏差={hi['return_pct'].std():.2f}")
        if not lo.empty:
            print(f"  低信頼度(n={len(lo)}): 平均={lo['return_pct'].mean():.2f}% "
                  f"中央値={lo['return_pct'].median():.2f}% 勝率={(lo['return_pct']>0).mean()*100:.1f}% "
                  f"標準偏差={lo['return_pct'].std():.2f}")
        print(f"\n  ※ ゴールデンクロスはフィルターなしで運用（検証の結果、絞り込み効果が確認できなかったため）")

    # --- 商品カテゴリ別 ---
    print(f"\n{'-' * 70}")
    print("商品カテゴリ別の成績（レバレッジ/インバース商品は分けて見る）")
    print(f"{'-' * 70}")
    for signal in ["ゴールデンクロス", "デッドクロス"]:
        sub = bt_df[bt_df["signal"] == signal]
        if sub.empty:
            continue
        print(f"\n■ {signal}")
        cat_g = sub.groupby("category")["return_pct"].agg(["count", "mean", "median", "std"])
        cat_g["win_rate"] = sub.groupby("category")["return_pct"].apply(lambda x: (x > 0).mean() * 100)
        print(cat_g.round(2))

    # --- 相場局面別（下落局面 vs 通常/上昇局面） ---
    print(f"\n{'-' * 70}")
    print("相場局面別の成績（下落局面での挙動を確認）")
    print(f"{'-' * 70}")
    for signal in ["ゴールデンクロス", "デッドクロス"]:
        sub = bt_df[bt_df["signal"] == signal]
        if sub.empty:
            continue
        print(f"\n■ {signal}")
        reg_g = sub.groupby("regime")["return_pct"].agg(["count", "mean", "median", "std"])
        reg_g["win_rate"] = sub.groupby("regime")["return_pct"].apply(lambda x: (x > 0).mean() * 100)
        print(reg_g.round(2))

    print(f"\n{'=' * 70}")
    print("※ 件数が少ない区分（目安10件未満）は統計的信頼性が低いため参考程度に。")
    print("※ 平均値はレバレッジ/個別株の極端な値に引っ張られやすいので、中央値も")
    print("  あわせて確認してください。")
    print(f"{'=' * 70}")


# ------------------------------------------------------------
# メイン処理
# ------------------------------------------------------------

def main():
    end = datetime.today()
    start = datetime.strptime(BACKTEST_START_DATE, "%Y-%m-%d")

    fx_rate = fetch_usd_jpy_rate()
    print(f"為替レート（米国株の円換算に使用）: 1ドル = {fx_rate:.2f}円\n")

    all_signals = []
    all_backtest_records = []
    all_approaching = []
    chart_records = []
    track_record = load_track_record()

    for ticker in TICKERS:
        try:
            df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
            if df.empty:
                print(f"{ticker}: データ取得失敗")
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = sanitize_price_series(df, ticker)
            df = compute_indicators(df)

            signals = get_recent_signals(ticker, df, fx_rate)
            all_signals.extend(signals)
            all_backtest_records.extend(backtest_ticker(ticker, df))
            all_approaching.extend(get_approaching_crosses(ticker, df))
            track_record = update_track_record(track_record, ticker, df)

            if signals:
                chart_df = df.tail(CHART_LOOKBACK_DAYS)[["Close", "EMA10", "EMA20"]].reset_index()
                chart_df.columns = ["Date", "Close", "EMA10", "EMA20"]
                chart_df["Date"] = chart_df["Date"].dt.strftime("%Y-%m-%d")
                chart_df["ティッカー"] = ticker
                chart_records.append(chart_df)

        except Exception as e:
            print(f"{ticker}: エラー ({e})")

    print(f"{'=' * 70}")
    print(f"直近{RECENT_CROSS_DAYS}日以内のシグナル")
    print(f"{'=' * 70}\n")

    if all_signals:
        sig_df = pd.DataFrame(all_signals)
        for _, r in sig_df.iterrows():
            print(f"[{r['判定']}] {r['ティッカー']}({r['カテゴリ']}) - {r['シグナル']} "
                  f"({r['発生日']}, 終値{r['終値']})")
        sig_df.to_csv("ma_cross_signals.csv", index=False, encoding="utf-8-sig")
        print("\n結果を ma_cross_signals.csv に保存しました。")
    else:
        print("直近でクロスが発生した銘柄はありませんでした。")

    if all_approaching:
        print(f"\n{'=' * 70}")
        print("クロス接近中（早期警告）")
        print(f"{'=' * 70}")
        app_df = pd.DataFrame(all_approaching)
        for _, r in app_df.iterrows():
            print(f"[接近中] {r['ティッカー']}({r['カテゴリ']}) - {r['接近中のシグナル']}方向 "
                  f"(乖離率{r['乖離率(%)']}%, 終値{r['終値']})")
        app_df.to_csv("ma_cross_approaching.csv", index=False, encoding="utf-8-sig")

    if chart_records:
        pd.concat(chart_records, ignore_index=True).to_csv(
            CHART_DATA_FILE, index=False, encoding="utf-8-sig"
        )

    save_track_record(track_record)
    resolved_recent = [r for r in track_record if r["resolved"]][-20:]
    if resolved_recent:
        win_rate = sum(1 for r in resolved_recent if r["return_pct"] > 0) / len(resolved_recent) * 100
        print(f"\n実運用シグナルの直近実績（直近{len(resolved_recent)}件）: 勝率{win_rate:.1f}%")

    summarize_backtest(all_backtest_records)

    if all_backtest_records:
        pd.DataFrame(all_backtest_records).to_csv(
            "ma_cross_backtest.csv", index=False, encoding="utf-8-sig"
        )
        print("\nバックテスト詳細（条件別）を ma_cross_backtest.csv に保存しました。")


if __name__ == "__main__":
    main()
