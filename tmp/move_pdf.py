import sys, shutil, pathlib
sys.stdout.reconfigure(encoding='utf-8')

base = pathlib.Path(r"d:\## Workspace(model4, April)")
add_dir = base / 'add'
add_dir.mkdir(exist_ok=True)
print("add/ 폴더:", add_dir.exists())

matches = list(base.glob('*24-0696*'))
print("발견:", [m.name for m in matches])

if matches:
    src = matches[0]
    dst = add_dir / src.name
    shutil.copy2(str(src), str(dst))
    src.unlink()
    print('이동 완료:', dst.name)
