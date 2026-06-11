from jarvis.remote.token import load_or_create_token


def test_creates_token_with_0600(tmp_path):
    p = tmp_path / "remote_token"
    tok = load_or_create_token(p)
    assert len(tok) >= 32
    assert p.read_text().strip() == tok
    assert (p.stat().st_mode & 0o777) == 0o600


def test_reuses_existing_token(tmp_path):
    p = tmp_path / "remote_token"
    first = load_or_create_token(p)
    assert load_or_create_token(p) == first


def test_regenerates_empty_file(tmp_path):
    p = tmp_path / "remote_token"
    p.write_text("  \n")
    tok = load_or_create_token(p)
    assert tok.strip()


def test_existing_file_perms_renarrowed(tmp_path):
    p = tmp_path / "remote_token"
    p.write_text("tok123\n")
    p.chmod(0o644)
    assert load_or_create_token(p) == "tok123"
    assert (p.stat().st_mode & 0o777) == 0o600
