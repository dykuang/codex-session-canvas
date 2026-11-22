#!/usr/bin/env python3
"""Install this directory's minimal Codex Skill without overwriting by default."""
import argparse
import shutil
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--destination',type=Path,default=Path.home()/'.agents'/'skills'/'codex-session-canvas')
p.add_argument('--force',action='store_true')
a=p.parse_args()
root=Path(__file__).resolve().parent
dest=a.destination.expanduser().resolve(strict=False)
if dest.exists():
    if not a.force:
        p.error(f'Will not overwrite existing skill at {dest}; pass --force to replace')
    shutil.rmtree(dest)
dest.mkdir(parents=True,exist_ok=False)
for item in ['SKILL.md','canvas.py','project_registry.py','project_bridge.py','project_server.py']:
    shutil.copy2(root/item,dest/item)
shutil.copytree(root/'web',dest/'web')
print(f'Codex skill installed: {dest}')
print('In Codex, invoke $codex-session-canvas or ask: 打开会话画布')
