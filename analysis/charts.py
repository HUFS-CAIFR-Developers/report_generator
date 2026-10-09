from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import config

plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False

# 문서 템플릿이 차트 위에 "그림 N. ..." 캡션을 자체적으로 표시하므로
# matplotlib 쪽에서는 제목을 넣지 않고 그래프만 깔끔하게 생성한다.
_MAIN_FIGSIZE = (9, 3.2)  # 문서 내 폭 180mm(전체 폭) 삽입용
_SUB_FIGSIZE = (5, 3.2)  # 문서 내 폭 90mm(2열 배치) 삽입용


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _main_price_chart(df: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=_MAIN_FIGSIZE)
    ax.plot(df["time"], df["close"], color="#2ca02c", linewidth=1.2)
    ax.set_ylabel("종가 (원)")
    ax.xaxis.set_major_locator(plt.MaxNLocator(6))
    fig.autofmt_xdate(rotation=30)
    _save(fig, path)


def _ma_chart(recent: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=_SUB_FIGSIZE)
    ax.plot(recent["time"], recent["close"], label="close", color="black", linewidth=1.2)
    for period in config.MA_PERIODS:
        col = f"ma{period}"
        if col in recent:
            ax.plot(recent["time"], recent[col], label=f"MA({period})", linewidth=1)
    ax.legend(fontsize=6, ncol=3, loc="best")
    ax.xaxis.set_major_locator(plt.MaxNLocator(4))
    fig.autofmt_xdate(rotation=30)
    _save(fig, path)


def _bollinger_chart(recent: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=_SUB_FIGSIZE)
    ax.plot(recent["time"], recent["close"], label="close", color="black", linewidth=1.2)
    ax.plot(recent["time"], recent["bb_upper"], label="Upper band", color="#2ca02c", linewidth=1)
    ax.plot(recent["time"], recent["bb_lower"], label="Lower band", color="#2ca02c", linewidth=1)
    ax.fill_between(recent["time"], recent["bb_lower"], recent["bb_upper"], alpha=0.08, color="#7f7f7f")
    ax.legend(fontsize=6, ncol=3, loc="best")
    ax.xaxis.set_major_locator(plt.MaxNLocator(4))
    fig.autofmt_xdate(rotation=30)
    _save(fig, path)


def _macd_chart(recent: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=_SUB_FIGSIZE)
    ax.plot(recent["time"], recent["macd"], label="MACD", color="#2ca02c", linewidth=1.2)
    ax.plot(recent["time"], recent["macd_signal"], label="signal", color="#d62728", linewidth=1.2)
    ax.axhline(0, color="#999999", linewidth=0.8)
    ax.legend(fontsize=6, ncol=2, loc="best")
    ax.xaxis.set_major_locator(plt.MaxNLocator(4))
    fig.autofmt_xdate(rotation=30)
    _save(fig, path)


def _rsi_chart(recent: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=_SUB_FIGSIZE)
    ax.plot(recent["time"], recent["rsi"], color="#2ca02c", linewidth=1.2)
    ax.set_ylim(0, 100)
    ax.xaxis.set_major_locator(plt.MaxNLocator(4))
    fig.autofmt_xdate(rotation=30)
    _save(fig, path)


def _stoch_chart(recent: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=_SUB_FIGSIZE)
    ax.plot(recent["time"], recent["stoch_k"], label="Slow %K", color="#d62728", linewidth=1.2)
    ax.plot(recent["time"], recent["stoch_d"], label="Slow %D", color="#2ca02c", linewidth=1.2)
    ax.set_ylim(0, 100)
    ax.legend(fontsize=6, ncol=2, loc="best")
    ax.xaxis.set_major_locator(plt.MaxNLocator(4))
    fig.autofmt_xdate(rotation=30)
    _save(fig, path)


def _volume_chart(recent: pd.DataFrame, path: Path):
    """원본 거래량이 아니라 20일 평균 대비 변화율(%)을 그린다."""
    fig, ax = plt.subplots(figsize=_SUB_FIGSIZE)
    ax.plot(recent["time"], recent["volume_change_20d"], color="#2ca02c", linewidth=1.2)
    ax.axhline(0, color="#999999", linewidth=0.8)
    ax.set_ylabel("percent")
    ax.xaxis.set_major_locator(plt.MaxNLocator(4))
    fig.autofmt_xdate(rotation=30)
    _save(fig, path)


def generate_company_charts(df: pd.DataFrame, n: int, out_dir: Path) -> dict[str, Path]:
    """기업당 7개 차트 PNG를 생성해 {placeholder_key: path} 딕셔너리로 반환."""
    recent = df.tail(config.TECH_CHART_LOOKBACK_DAYS).reset_index(drop=True)

    paths = {
        f"chart{n}": out_dir / f"chart{n}.png",
        f"chart{n}_tech_ma": out_dir / f"chart{n}_tech_ma.png",
        f"chart{n}_tech_boll": out_dir / f"chart{n}_tech_boll.png",
        f"chart{n}_tech_macd": out_dir / f"chart{n}_tech_macd.png",
        f"chart{n}_tech_rsi": out_dir / f"chart{n}_tech_rsi.png",
        f"chart{n}_tech_stoch": out_dir / f"chart{n}_tech_stoch.png",
        f"chart{n}_tech_vol": out_dir / f"chart{n}_tech_vol.png",
    }

    _main_price_chart(df, paths[f"chart{n}"])
    _ma_chart(recent, paths[f"chart{n}_tech_ma"])
    _bollinger_chart(recent, paths[f"chart{n}_tech_boll"])
    _macd_chart(recent, paths[f"chart{n}_tech_macd"])
    _rsi_chart(recent, paths[f"chart{n}_tech_rsi"])
    _stoch_chart(recent, paths[f"chart{n}_tech_stoch"])
    _volume_chart(recent, paths[f"chart{n}_tech_vol"])

    return paths
