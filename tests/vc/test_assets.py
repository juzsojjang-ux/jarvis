from pathlib import Path

from jarvis.vc.assets import ensure_assets, missing_assets


def test_downloads_missing_then_caches(tmp_path):
    calls = []

    def fake_dl(repo_id, repo_file, target):
        calls.append(repo_id)
        Path(target).write_text("x")
        return target

    out = ensure_assets(tmp_path, downloader=fake_dl)
    assert len(out) == 2 and len(calls) == 2

    # 두 번째 호출은 캐시 — 다운로드 안 함
    calls.clear()
    ensure_assets(tmp_path, downloader=fake_dl)
    assert calls == []


def test_missing_assets_lists_absent(tmp_path):
    assert len(missing_assets(tmp_path)) == 2
    (tmp_path / "rmvpe.pt").write_text("x")
    assert "rmvpe.pt" not in missing_assets(tmp_path)


def test_download_failure_skipped_gracefully(tmp_path):
    def boom(repo_id, repo_file, target):
        raise RuntimeError("offline")

    out = ensure_assets(tmp_path, downloader=boom)
    assert out == {}  # 실패해도 raise 안 함
