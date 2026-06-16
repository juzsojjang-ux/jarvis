"""HF 캐시 tar.gz를 '심볼릭 없이' 전개한다 — 윈도우(심볼릭 생성 권한 없음)에서도 동작.

huggingface_hub 캐시는 snapshots/<rev>/.../model.safetensors 가 ../../blobs/<sha> 를
가리키는 심볼릭이다. 윈도우 tar는 이 심볼릭을 못 만들고 멈춘다(Cannot create symlink).
이 스크립트는 1) 일반 파일을 먼저 풀고 2) 심볼릭/하드링크는 '타깃을 실제 복사'로 만들어,
플랫폼·번들러와 무관하게 오프라인 로드가 되도록 보장한다.

사용: python extract_hf_tar.py <tar.gz> <dest_dir>
"""
from __future__ import annotations

import os
import shutil
import sys
import tarfile


def extract(tar_path: str, dest: str) -> int:
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(tar_path, "r:*") as tf:
        members = tf.getmembers()
        for m in members:                       # 1) 디렉토리
            if m.isdir():
                os.makedirs(os.path.join(dest, m.name), exist_ok=True)
        for m in members:                       # 2) 일반 파일(blobs 포함)
            if m.isfile() and not m.issym() and not m.islnk():
                tf.extract(m, dest)
        copied = 0
        for m in members:                       # 3) 심볼릭/하드링크 → 타깃 실제 복사
            if not (m.issym() or m.islnk()):
                continue
            link = os.path.join(dest, m.name)
            if m.issym():                        # linkname은 링크 위치 기준 상대경로
                target = os.path.normpath(os.path.join(os.path.dirname(link), m.linkname))
            else:                                # 하드링크는 아카이브 루트 기준
                target = os.path.join(dest, m.linkname)
            os.makedirs(os.path.dirname(link), exist_ok=True)
            if os.path.isfile(target):
                if os.path.lexists(link):
                    os.remove(link)
                shutil.copy2(target, link)
                copied += 1
            else:
                print(f"  경고: 링크 타깃 없음 {m.name} -> {m.linkname}", file=sys.stderr)
    return copied


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용: python extract_hf_tar.py <tar.gz> <dest_dir>", file=sys.stderr)
        sys.exit(2)
    n = extract(sys.argv[1], sys.argv[2])
    print(f"[extract_hf_tar] {n} link(s) materialized -> {sys.argv[2]}")
