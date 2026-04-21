import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

manifest_path = Path('data/qa_precedents/manifest.json')
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
before = len(manifest.get('indexed', []))
manifest['indexed'] = [x for x in manifest.get('indexed', []) if '0696' not in x.get('file', '')]
after = len(manifest['indexed'])
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'manifest: {before} → {after}개 (24-0696 제거)')
