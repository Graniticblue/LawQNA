#!/usr/bin/env python3
"""
scripts/add_related_amendments.py
-- amendments.jsonl에 연관_개정 필드 추가 (주제 그룹 기반 연쇄 개정 추적)

사용:
  python scripts/add_related_amendments.py
"""

import json
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent.parent
AMENDMENTS_PATH = BASE_DIR / "data" / "law_amendments" / "amendments.jsonl"

# ── 주제 그룹 (하드코딩) ───────────────────────────────────────
theme_groups: dict[str, list[str]] = {
    "방화문": ["방화문", "갑종방화문", "60분+", "을종"],
    "방화구획": ["방화구획", "자동방화셔터"],
    "소방관진입창": ["소방관 진입", "진입창"],
    "외벽마감재료": ["외벽 마감", "마감재료", "단열재", "복합자재"],
    "내화구조": ["내화구조", "지붕", "주요구조부"],
    "공사감리": ["공사감리", "감리자", "감리중간보고서"],
    "필로티": ["필로티", "필로티형식"],
    "지하주차장": ["지하주차장", "경사로"],
    "공개공지": ["공개공지", "공개공간"],
    "결합건축": ["결합건축"],
    "이행강제금": ["이행강제금"],
}


def extract_text_for_matching(rec: dict) -> str:
    """레코드의 개정이유 + 목적론적_키포인트 텍스트 추출."""
    parts = []

    이유 = rec.get("개정이유", "")
    if 이유:
        parts.append(이유)

    kp = rec.get("목적론적_키포인트", "")
    if isinstance(kp, list):
        parts.extend(kp)
    elif kp:
        parts.append(kp)

    # 주요내용에서도 키워드 추출
    주요내용 = rec.get("주요내용", "")
    if isinstance(주요내용, list):
        for item in 주요내용:
            if isinstance(item, dict):
                항목 = item.get("항목", "")
                내용 = item.get("내용", "")
                if 항목:
                    parts.append(항목)
                if 내용:
                    parts.append(내용)
    elif isinstance(주요내용, str) and 주요내용:
        parts.append(주요내용)

    return " ".join(parts)


def find_themes_for_record(rec: dict) -> set[str]:
    """레코드가 속하는 주제 그룹 이름 집합 반환."""
    text = extract_text_for_matching(rec)
    matched_themes: set[str] = set()
    for theme_name, keywords in theme_groups.items():
        for kw in keywords:
            if kw in text:
                matched_themes.add(theme_name)
                break  # 해당 테마는 이미 매칭됨
    return matched_themes


def load_amendments() -> list[dict]:
    if not AMENDMENTS_PATH.exists():
        print(f"[ERROR] amendments.jsonl 없음: {AMENDMENTS_PATH}")
        raise FileNotFoundError(str(AMENDMENTS_PATH))
    records = []
    with open(AMENDMENTS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] JSON 파싱 실패: {e}")
    return records


def main():
    print(f"amendments.jsonl 로드 중: {AMENDMENTS_PATH}")
    records = load_amendments()
    print(f"  → {len(records)}건 로드 완료")

    # 각 레코드의 주제 그룹 계산
    record_themes: list[set[str]] = []
    for rec in records:
        themes = find_themes_for_record(rec)
        record_themes.append(themes)
        if themes:
            print(f"  [{rec.get('amendment_id','')}] 주제: {', '.join(themes)}")

    # 연관_개정 계산: 같은 테마를 공유하는 다른 레코드들
    updated_count = 0
    for i, rec in enumerate(records):
        my_themes = record_themes[i]
        my_id = rec.get("amendment_id", "")
        if not my_themes:
            # 매칭 테마 없으면 연관_개정 빈 리스트로 설정
            rec["연관_개정"] = []
            continue

        related: list[str] = []
        for j, other_rec in enumerate(records):
            if i == j:
                continue  # 자기 자신 제외
            other_id = other_rec.get("amendment_id", "")
            other_themes = record_themes[j]
            # 테마 교집합이 있으면 연관
            if my_themes & other_themes:
                related.append(other_id)

        rec["연관_개정"] = related
        if related:
            updated_count += 1
            print(f"  [{my_id}] 연관_개정 {len(related)}건: {related[:3]}{'...' if len(related) > 3 else ''}")

    # amendments.jsonl 업데이트
    print(f"\namendments.jsonl 업데이트 중...")
    with open(AMENDMENTS_PATH, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"완료: {updated_count}건에 연관_개정 필드 추가됨 (총 {len(records)}건 중)")


if __name__ == "__main__":
    main()
