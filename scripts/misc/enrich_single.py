"""단일 JSONL 파일만 enrich"""
import sys
from pathlib import Path

# enrich_법제처의 enrich_file 함수 재사용
sys.path.insert(0, str(Path(__file__).parent))
from enrich_법제처 import enrich_file

target = Path("data/qa_precedents/updates/법제처_21-0640.jsonl")
enrich_file(target)
print("\n완료")
