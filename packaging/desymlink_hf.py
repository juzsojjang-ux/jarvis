"""HF 캐시 디렉토리의 심볼릭 링크를 '실제 파일 복사'로 치환한다 (인자: 루트 경로).

왜: huggingface_hub 캐시는 snapshots/<rev>/.../model.safetensors 가 blobs/<sha> 를
가리키는 심볼릭이다. 윈도우는 심볼릭 생성 권한이 없을 수 있고, tar 전개·번들 과정에서
링크가 깨지면 오프라인 모델 로드가 실패한다(Pocket 무음). 모든 파일 심볼릭을 실파일
복사로 만들어 플랫폼·번들러와 무관하게 로드되게 한다. 멱등(심볼릭 없으면 no-op)."""
from __future__ import annotations

import os
import shutil
import sys


def materialize(root: str) -> int:
    links: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            p = os.path.join(dirpath, name)
            if os.path.islink(p):
                links.append(p)
    n = 0
    for p in links:
        target = os.path.realpath(p)
        if os.path.isfile(target):
            os.remove(p)
            shutil.copy2(target, p)
            n += 1
    return n


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    count = materialize(root)
    print(f"[desymlink] {count} symlink(s) materialized under {root}")
