import pandas as pd
import yfinance as yf

import config


def _is_real_listing(ticker: yf.Ticker, symbol: str) -> bool:
    """Yahoo Finance에는 실제 종목이 아닌 placeholder 심볼도 존재한다(예: 코스닥 종목의
    잘못된 .KS 버전). 이런 placeholder는 history()나 가격 필드도 그럴듯한 값을 반환할 수
    있지만, longName/shortName이 실제 회사명이 아니라 "{심볼},{내부ID},..." 형태의
    자동생성 문자열이다. 이 패턴으로 걸러낸다."""
    try:
        info = ticker.info
    except Exception:
        return False

    name = info.get("longName") or info.get("shortName") or ""
    if name.startswith(symbol + ","):
        return False
    return bool(name)


def _resolve_yf_ticker(ticker_code: str) -> tuple[str, pd.DataFrame]:
    """국내 종목코드는 거래소 접미사(.KS 코스피 / .KQ 코스닥)가 필요.
    어느 쪽인지 미리 알 수 없으므로 순서대로 시도하되, 실거래 정보가 없는
    placeholder 심볼(잘못된 시장 접미사)은 걸러낸다."""
    for suffix in (".KS", ".KQ"):
        symbol = f"{ticker_code}{suffix}"
        ticker = yf.Ticker(symbol)
        if not _is_real_listing(ticker, symbol):
            continue
        df = ticker.history(period=config.STOCK_HISTORY_RANGE, interval="1d")
        if not df.empty:
            return symbol, df
    raise ValueError(f"yfinance에서 실제 상장 데이터를 찾을 수 없음: {ticker_code} (.KS/.KQ 모두 실패)")


def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _stoch_rsi(rsi: pd.Series, length: int) -> tuple[pd.Series, pd.Series]:
    rsi_min = rsi.rolling(length).min()
    rsi_max = rsi.rolling(length).max()
    raw_k = (rsi - rsi_min) / (rsi_max - rsi_min) * 100
    slow_k = raw_k.rolling(3).mean()
    slow_d = slow_k.rolling(3).mean()
    return slow_k, slow_d


def _macd(close: pd.Series, fast: int, slow: int, signal: int) -> tuple[pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def _bollinger(close: pd.Series, length: int, num_std: float) -> tuple[pd.Series, pd.Series]:
    mid = close.rolling(length).mean()
    std = close.rolling(length).std()
    return mid + num_std * std, mid - num_std * std


def fetch_technical_data(ticker_code: str) -> pd.DataFrame:
    """종목코드로 OHLCV + 기술적 지표를 계산해 하나의 DataFrame으로 반환."""
    symbol, raw = _resolve_yf_ticker(ticker_code)

    df = pd.DataFrame({
        "time": raw.index.strftime("%Y-%m-%d"),
        "open": raw["Open"].values,
        "high": raw["High"].values,
        "low": raw["Low"].values,
        "close": raw["Close"].values,
        "volume": raw["Volume"].values,
    })
    close = df["close"]
    volume = df["volume"]

    df["rsi"] = _rsi(close, config.RSI_LENGTH)
    df["stoch_k"], df["stoch_d"] = _stoch_rsi(df["rsi"], config.STOCH_RSI_LENGTH)
    df["macd"], df["macd_signal"] = _macd(close, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL)
    df["bb_upper"], df["bb_lower"] = _bollinger(close, config.BB_LENGTH, config.BB_STD)

    for period in config.MA_PERIODS:
        df[f"ma{period}"] = close.rolling(period).mean()

    vol_avg = volume.rolling(config.VOLUME_AVG_PERIOD).mean()
    df["volume_change_20d"] = (volume - vol_avg) / vol_avg * 100

    df.attrs["yf_symbol"] = symbol
    return df
