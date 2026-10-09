import sys
from datetime import datetime

import config
from analysis.charts import generate_company_charts
from analysis.company_pick import pick_companies
from analysis.market_topic import identify_dominant_topic, write_market_briefing
from analysis.report_writer import (
    generate_final_title_summary,
    generate_report_title,
    one_sentence_conclusion,
    write_investment_analysis,
    write_technical_analysis,
)
from analysis.summarize import extract_key_sentence, summarize_article
from analysis.summary_card import generate_summary_card
from analysis.text_utils import to_plain_text as _plain
from report.build_doc import build_report
from report.telegram_notify import send_docx_private, send_report
from sources.article import fetch_article
from sources.naver_ranking import fetch_economy_headlines
from sources.stock import fetch_technical_data


def _build_report(article_title: str, article_summary: str, article_key_sentence: str):
    """기사 제목/요약/핵심문장이 주어지면 관련 기업 선정부터 문서 생성까지 나머지 전체를 처리한다.
    수동 실행(기사 1건)과 자동 실행(오늘의 시황) 양쪽에서 공유하는 본체."""
    print("관련 기업 선정 중...")
    companies = pick_companies(_plain(article_summary))
    if not companies:
        raise RuntimeError("관련 기업을 하나도 매칭하지 못했습니다.")
    print("선정된 기업: " + ", ".join(c["corp_name"] for c in companies))

    context = {
        "article_title": article_title,
        "article_content": article_summary,
        "article_summary1": article_key_sentence,
    }
    chart_paths = {}
    report_pieces = [article_summary]

    for i, company in enumerate(companies, start=1):
        print(f"{i}. {company['corp_name']}({company['ticker']}) 분석 중...")

        content = write_investment_analysis(
            company["corp_name"], company["ticker"], company["reason"], _plain(article_summary)
        )
        content_conclusion = one_sentence_conclusion(_plain(content))

        tech_df = fetch_technical_data(company["ticker"])
        tech_content = write_technical_analysis(company["corp_name"], company["ticker"], tech_df)
        tech_conclusion = one_sentence_conclusion(_plain(tech_content))

        charts = generate_company_charts(tech_df, i, config.CHART_TMP_DIR)
        chart_paths.update(charts)

        context[f"company{i}"] = company["corp_name"]
        context[f"company{i}_ticker"] = company["ticker"]
        context[f"company{i}_content"] = content
        context[f"company{i}_summary"] = content_conclusion
        context[f"company{i}_tec_content"] = tech_content
        context[f"company{i}_tec_summary"] = tech_conclusion

        report_pieces.append(content)
        report_pieces.append(tech_content)

    print("최종 제목/요약 생성 중...")
    full_text = "\n\n".join(_plain(p) for p in report_pieces)
    context["title"] = generate_report_title(full_text)
    final_title, final_summary = generate_final_title_summary(full_text)
    context["final_title"] = final_title
    context["final_summary"] = final_summary
    context["date"] = datetime.now().strftime("%Y.%m.%d")

    print("문서 생성 중...")
    out_path = build_report(context, chart_paths)
    date_dash = datetime.now().strftime("%Y-%m-%d")

    # docx는 Word 자동화 없이 만들어지므로 PDF 변환(느리거나 멈출 수 있음)을 기다리지 않고
    # 만들어지자마자 바로 비공개 채널로 보낸다.
    print("docx 원본 비공개 전송 중...")
    docx_message = f"📄 {date_dash} 원본 docx\n\"{context['title']}\""
    if send_docx_private(out_path, docx_message):
        print("docx 비공개 전송 완료")
    else:
        print("docx 비공개 전송 건너뜀 (설정 없음 또는 실패)")

    print("요약 카드 이미지 생성 중...")
    card_path = generate_summary_card(context, config.OUTPUT_DIR / f"{out_path.stem}_card.png")

    print("텔레그램 전송 중 (카드+텍스트)...")
    message_text = (
        f"📝 {date_dash} 시황분석 리포트\n\n"
        f"\"{context['title']}\"\n\n"
        f"자세한 내용은 아래 첨부파일을 참고하세요."
    )
    if send_report(None, message_text, card_path=card_path):
        print("카드+텍스트 전송 완료")
    else:
        print("카드+텍스트 전송 건너뜀 (설정 없음 또는 실패)")

    # PDF 변환/서버 업로드는 자동화에서 뺐다 - PDF는 사용자가 비공개 채널로 받은 docx를
    # 직접 변환해서 처리한다.
    return out_path, None


def run(url: str):
    """수동 실행: 기사 URL 1개 → 리포트."""
    print("기사를 가져오는 중...")
    article = fetch_article(url)

    print("기사 요약 중...")
    article_summary = summarize_article(article["content"])
    article_key_sentence = extract_key_sentence(article["content"])

    return _build_report(article["title"], article_summary, article_key_sentence)


def run_auto():
    """자동 실행: 오늘 네이버 경제면 헤드라인 → 오늘의 시황 브리핑 → 리포트."""
    print("오늘의 경제 뉴스 헤드라인 수집 중...")
    headlines = fetch_economy_headlines()
    if not headlines:
        raise RuntimeError("경제면 헤드라인을 하나도 가져오지 못했습니다.")
    print(f"헤드라인 {len(headlines)}건 수집")

    print("핵심 이슈 분석 중...")
    topic = identify_dominant_topic(headlines)
    print(f"오늘의 핵심 이슈: {topic['dominant_topic']}")

    print("오늘의 시황 브리핑 작성 중...")
    briefing = write_market_briefing(topic)
    briefing_key_sentence = extract_key_sentence(_plain(briefing))

    return _build_report(topic["dominant_topic"][:40], briefing, briefing_key_sentence)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--auto":
        out_path, pdf_path = run_auto()
    else:
        url = input("기사 URL을 입력하세요: ").strip()
        if not url:
            print("URL이 입력되지 않았습니다.")
            sys.exit(1)
        out_path, pdf_path = run(url)

    print(f"\n완료: {out_path}")
    if pdf_path:
        print(f"PDF: {pdf_path}")


if __name__ == "__main__":
    main()
