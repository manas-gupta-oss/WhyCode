import pytest

from whycode.extract.entities import (
    PathOutsideRepoError,
    parse_source,
)
from whycode.ids import make_id

REPO = "psf/requests"


# ---------- files ----------


def test_simple_file_entity():
    parsed = parse_source("x = 1\n", "pkg/mod.py", REPO)
    f = parsed.file
    assert f.kind == "File"
    assert f.id == "psf/requests#file:pkg/mod.py" == make_id(REPO, "file", "pkg/mod.py")
    assert f.name == "mod.py"
    assert f.file_path == "pkg/mod.py"
    assert f.repo == REPO
    assert f.line_count == 1
    assert not parsed.has_syntax_errors
    assert parsed.entities == [f]


def test_windows_style_path_is_normalized_to_posix():
    assert parse_source("", "pkg\\mod.py", REPO).file.file_path == "pkg/mod.py"


@pytest.mark.parametrize("bad", ["../x.py", "a/../../x.py", "/etc/x.py", "C:/x.py", "", "."])
def test_parse_source_rejects_non_relative_paths(bad):
    with pytest.raises(PathOutsideRepoError):
        parse_source("", bad, REPO)


def test_empty_file():
    parsed = parse_source(b"", "empty.py", REPO)
    assert parsed.file.line_count == 0
    assert (parsed.classes, parsed.functions, parsed.config_keys) == ((), (), ())
    assert not parsed.has_syntax_errors


def test_comments_only_file():
    parsed = parse_source("# just a comment\n# another\n", "c.py", REPO)
    assert parsed.file.line_count == 2
    assert parsed.entities == [parsed.file]
    assert not parsed.has_syntax_errors
