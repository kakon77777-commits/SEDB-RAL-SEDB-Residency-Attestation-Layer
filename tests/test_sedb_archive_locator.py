from sedb_archive_locator import locate_sedb_v04b_archive


def test_explicit_override_wins_without_silent_fallback(tmp_path):
    explicit = tmp_path / "missing-explicit.zip"
    env_archive = tmp_path / "env.zip"
    env_archive.write_bytes(b"env")

    assert locate_sedb_v04b_archive(
        explicit=explicit,
        environ={"SEDB_V04B_ARCHIVE": str(env_archive)},
        start=tmp_path,
    ) == explicit.resolve()


def test_environment_override_wins_before_sibling(tmp_path):
    env_archive = tmp_path / "env.zip"
    env_archive.write_bytes(b"env")

    assert locate_sedb_v04b_archive(
        environ={"SEDB_V04B_ARCHIVE": str(env_archive)},
        start=tmp_path,
    ) == env_archive.resolve()


def test_repo_sibling_release_is_discovered_from_linked_worktree(tmp_path):
    family = tmp_path / "work together"
    start = family / "SEDB-RAL" / ".worktrees" / "feature"
    start.mkdir(parents=True)
    archive = family / "SEDB" / "releases" / "SEDB-v0.4B-local.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"release")

    assert locate_sedb_v04b_archive(environ={}, start=start) == archive.resolve()


def test_absent_override_and_sibling_returns_none(tmp_path):
    assert locate_sedb_v04b_archive(environ={}, start=tmp_path) is None
