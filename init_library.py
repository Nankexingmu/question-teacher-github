"""Create a local, untracked library from the clean repository template."""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "library-template"
LIBRARY = ROOT / "library"


def main() -> None:
    if LIBRARY.exists():
        print(f"资料库已存在，未覆盖：{LIBRARY}")
        return
    shutil.copytree(TEMPLATE, LIBRARY)
    print(f"已创建本机资料库：{LIBRARY}")
    print("现在可以上传自己的教材或试卷，并逐步核对入库。")


if __name__ == "__main__":
    main()
