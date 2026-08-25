"""
ma_cross_backtest.csv に含まれる cand_ 系（検証中）の条件について、
win_rate（return_pct > 0 の割合）に有意差があるかを二標本比率のz検定で
検証する。既存の cond_ 系（デッドクロスの2条件）と同じ考え方・同じ有意水準
で判定し、有意だった条件だけを evaluate_conditions() の cond_ に昇格させる
かどうかの判断材料にする。

使い方:
    python ma_cross_screener.py   # 先に最新の ma_cross_backtest.csv を生成
    python analyze_new_conditions.py
"""

import math

import pandas as pd

BACKTEST_CSV = "ma_cross_backtest.csv"
ALPHA = 0.01  # 既存の検証（p<0.0001, p=0.0004）に合わせ、厳しめの有意水準を採用


def z_test_two_proportions(x1: int, n1: int, x2: int, n2: int):
    if n1 == 0 or n2 == 0:
        return None, None
    p1, p2 = x1 / n1, x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return None, None
    z = (p1 - p2) / se
    p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return z, p_value


def main():
    df = pd.read_csv(BACKTEST_CSV, encoding="utf-8-sig")
    df["win"] = df["return_pct"] > 0

    cand_cols = [c for c in df.columns if c.startswith("cand_")]

    for signal in ["ゴールデンクロス", "デッドクロス"]:
        sub = df[df["signal"] == signal]
        print(f"\n{'=' * 78}")
        print(f"■ {signal}  (全体 n={len(sub)}, 全体勝率={sub['win'].mean()*100:.1f}%)")
        print(f"{'=' * 78}")

        for col in cand_cols:
            if col not in sub.columns:
                continue
            valid = sub[sub[col].notna()]
            if valid.empty:
                continue

            true_g = valid[valid[col] == True]  # noqa: E712
            false_g = valid[valid[col] == False]  # noqa: E712
            if len(true_g) < 10 or len(false_g) < 10:
                print(f"  {col}: サンプル不足のためスキップ (True n={len(true_g)}, False n={len(false_g)})")
                continue

            x1, n1 = int(true_g["win"].sum()), len(true_g)
            x2, n2 = int(false_g["win"].sum()), len(false_g)
            z, p = z_test_two_proportions(x1, n1, x2, n2)
            if z is None:
                continue

            win1, win2 = x1 / n1 * 100, x2 / n2 * 100
            mean1, mean2 = true_g["return_pct"].mean(), false_g["return_pct"].mean()
            mark = " ★有意" if p < ALPHA else ""
            print(f"  {col}{mark}")
            print(f"    True  (n={n1:>5}): 勝率{win1:5.1f}%  平均{mean1:+.2f}%")
            print(f"    False (n={n2:>5}): 勝率{win2:5.1f}%  平均{mean2:+.2f}%")
            print(f"    z={z:+.2f}  p={p:.5f}")


if __name__ == "__main__":
    main()
