#!/usr/bin/env python3
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# 06_Generator.py는 숫자로 시작해 import 불가 → spec_from_file_location 사용
import importlib.util
spec = importlib.util.spec_from_file_location(
    "generator",
    Path(__file__).parent.parent / "pipeline" / "06_Generator.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

bullets = mod.load_memo_bullets()
print(bullets)
print("\n---")
print(f"총 {len(bullets.splitlines())}개 always-on bullet 로드됨")
