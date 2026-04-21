import sys
sys.stdout.reconfigure(encoding='utf-8')

# Generator의 load_memo_bullets 함수 직접 테스트
import importlib.util
spec = importlib.util.spec_from_file_location("gen", "06_Generator.py")
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

bullets = mod.load_memo_bullets()
print(f"총 {len(bullets.splitlines())}개 bullet:\n")
print(bullets)
