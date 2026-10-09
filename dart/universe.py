import csv

import config


def load_universe() -> dict:
    """{종목코드: {"corp_name":.., "index": "KOSPI200"|"KOSDAQ150"}} 반환.
    data/index_universe.csv는 6개월마다(6월·12월 리밸런싱) 갱신이 필요함 - index_universe_meta.json 참고."""
    universe = {}
    with open(config.INDEX_UNIVERSE_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            universe[row["ticker"]] = {"corp_name": row["corp_name"], "index": row["index"]}
    return universe
