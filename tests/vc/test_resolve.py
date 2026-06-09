from jarvis.vc.resolve import resolve_index_path, resolve_model_path


def test_model_exact_path(tmp_path):
    pth = tmp_path / "jarvis.pth"
    pth.write_bytes(b"x")
    assert resolve_model_path(str(pth)) == str(pth)


def test_model_glob_when_named_differently(tmp_path):
    # user drops a differently-named export; configured jarvis.pth is absent
    other = tmp_path / "jarvis_e300.pth"
    other.write_bytes(b"x")
    assert resolve_model_path(str(tmp_path / "jarvis.pth")) == str(other)


def test_model_absent_returns_none(tmp_path):
    assert resolve_model_path(str(tmp_path / "jarvis.pth")) is None


def test_index_exact_path(tmp_path):
    (tmp_path / "jarvis.pth").write_bytes(b"x")
    idx = tmp_path / "jarvis.index"
    idx.write_bytes(b"x")
    assert resolve_index_path(str(tmp_path / "jarvis.pth"), str(idx)) == str(idx)


def test_index_added_glob(tmp_path):
    # RVC's real export name; configured jarvis.index is absent
    (tmp_path / "jarvis.pth").write_bytes(b"x")
    added = tmp_path / "added_IVF256_Flat_nprobe_1_jarvis_v2.index"
    added.write_bytes(b"x")
    assert resolve_index_path(str(tmp_path / "jarvis.pth"),
                              str(tmp_path / "jarvis.index")) == str(added)


def test_index_optional_returns_none(tmp_path):
    (tmp_path / "jarvis.pth").write_bytes(b"x")
    assert resolve_index_path(str(tmp_path / "jarvis.pth"),
                              str(tmp_path / "jarvis.index")) is None
