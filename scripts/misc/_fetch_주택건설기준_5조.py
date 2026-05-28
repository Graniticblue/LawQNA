import sys
sys.path.insert(0, '.')
from law_api_fetcher import fetch_article

result = fetch_article("주택건설기준 등에 관한 규정", "제5조")
print(result if result else "조문 없음 (삭제 또는 API 미조회)")
