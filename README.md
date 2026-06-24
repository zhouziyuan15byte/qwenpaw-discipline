# qwenpaw-discipline

Agent discipline enforcement for QwenPaw. One `install()` call patches four layers:

| Phase | What | How |
|:--:|------|------|
| 1 | 🚫 Gates | Block `browser_use stop`, kill Chrome, auto-fix `headed=false` |
| 2 | 🔍 Context | Pre-inject grep + file content before `write_file`, tab list before `browser_use open` |
| 4 | 🤝 Collab | Pre-inject target agent's `task_bridge` status before `chat_with_agent` |
| 5 | 📋 Recovery | Session-start card with last task + file change detection |

Design doc: [DESIGN.md](DESIGN.md)

## Install

```bash
pip install git+https://github.com/zhouziyuan15byte/qwenpaw-discipline.git
```

## Usage

```python
from qwenpaw_discipline import install
install()
```
