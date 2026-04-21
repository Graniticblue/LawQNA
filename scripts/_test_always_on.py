import sys
sys.stdout.reconfigure(encoding='utf-8')

import importlib.util
spec = importlib.util.spec_from_file_location("gen", "06_Generator.py")
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

bullets = mod.load_memo_bullets()
print("=== always-on bullets (PASS2 시스템 프롬프트 주입 내용) ===\n")
print(bullets)
print(f"\n총 {len(bullets.splitlines())}줄")
