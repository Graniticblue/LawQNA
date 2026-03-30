import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import importlib.util
spec = importlib.util.spec_from_file_location("generator", Path(__file__).parent / "06_Generator.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

query = """「건축법」 제14조(건축신고)에서 규정하는 '건축신고'의 범위에 같은 조 제1항제3호 및 제4호에 따른 대수선 신고도 포함되는 것인지? 다른 법령에서 "건축신고를 한 경우"라고 규정할 때 대수선 신고도 해당되는지?

[배경] 건축법 제14조는 조문 제목이 "건축신고"이나, 제1항에서 건축물을 '건축'하는 경우(제1호·제2호)뿐만 아니라 '대수선'하는 경우(제3호·제4호)도 동일한 조문에서 규정하고 있음. 이에 타 법령에서 "건축신고를 한 경우" 또는 "건축신고"를 요건으로 규정할 때, 대수선 신고가 포함되는지 여부가 쟁점임."""

gen = mod.Generator()
result = gen.generate(query, verbose=False)

out_path = Path(__file__).parent / "my_result.txt"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(result['answer'])

print(result['answer'])
