import io
import re
import time
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd
import requests
from rapidfuzz import fuzz, process

import config

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"


def _normalize(name: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", name).lower()


def _fetch_from_opendart() -> pd.DataFrame:
    resp = requests.get(CORP_CODE_URL, params={"crtfc_key": config.OPENDART_API_KEY}, timeout=30)
    resp.raise_for_status()

    if not resp.content.startswith(b"PK"):
        # 키 만료/한도 초과 등이면 zip 대신 <result><status>..</status><message>..</message>가 온다
        try:
            root = ET.fromstring(resp.content)
            detail = f"status={root.findtext('status')} {root.findtext('message')}"
        except ET.ParseError:
            detail = resp.content[:200].decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenDART가 기업목록 zip 대신 오류를 반환: {detail}")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_bytes = zf.read("CORPCODE.xml")

    root = ET.fromstring(xml_bytes)
    rows = []
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_name = (item.findtext("corp_name") or "").strip()
        if not stock_code:
            continue  # 비상장 기업 (종목코드 없음) 제외
        rows.append({"corp_name": corp_name, "ticker": stock_code})

    df = pd.DataFrame(rows).drop_duplicates(subset="ticker").reset_index(drop=True)
    df["normalized_name"] = df["corp_name"].map(_normalize)
    return df


def refresh_krx_master(force: bool = False) -> pd.DataFrame:
    cache_path = config.KRX_MASTER_CACHE
    if not force and cache_path.exists():
        age_days = (time.time() - cache_path.stat().st_mtime) / 86400
        if age_days < config.KRX_MASTER_MAX_AGE_DAYS:
            return pd.read_csv(cache_path, dtype={"ticker": str})

    try:
        df = _fetch_from_opendart()
    except Exception as e:
        # 상장사 목록은 거의 안 바뀌므로, 갱신 실패 시 오래된 캐시라도 있으면 그걸로 진행한다
        # (리포트가 통째로 안 나오는 것보다 낫다). 명시적 강제 갱신(force)은 실패를 그대로 올린다.
        if not force and cache_path.exists():
            print(f"[경고] OpenDART 기업목록 갱신 실패 - 기존 캐시 사용: {e}")
            return pd.read_csv(cache_path, dtype={"ticker": str})
        raise
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path, index=False)
    return df


def load_krx_master() -> pd.DataFrame:
    return refresh_krx_master(force=False)


def match_company(name: str, master: pd.DataFrame | None = None, score_cutoff: float = 85.0):
    """LLM이 답한 회사명을 KRX 마스터와 매칭해 {corp_name, ticker}를 반환. 실패 시 None."""
    if master is None:
        master = load_krx_master()

    normalized = _normalize(name)

    exact = master[master["normalized_name"] == normalized]
    if not exact.empty:
        row = exact.iloc[0]
        return {"corp_name": row["corp_name"], "ticker": row["ticker"]}

    choices = master["normalized_name"].tolist()
    result = process.extractOne(normalized, choices, scorer=fuzz.WRatio, score_cutoff=score_cutoff)
    if result is None:
        return None

    matched_normalized, score, idx = result
    row = master.iloc[idx]
    return {"corp_name": row["corp_name"], "ticker": row["ticker"]}
