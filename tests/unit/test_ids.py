import pytest

from whycode.ids import decision_id, make_id, normalize_repo, repo_id


def test_make_id_prefixes_repo():
    assert make_id("psf/requests", "pr", 1565) == "psf/requests#pr:1565"


def test_same_input_same_id():
    assert make_id("psf/requests", "issue", 812) == make_id("psf/requests", "issue", "812")


def test_repo_is_normalized_so_case_does_not_split_nodes():
    assert make_id("PSF/Requests", "pr", 1) == make_id(" psf/requests ", "pr", 1)


def test_two_repos_same_number_differ():
    assert make_id("psf/requests", "pr", 1565) != make_id("pallets/flask", "pr", 1565)


def test_commit_uses_commit_kind_and_lowercase_sha():
    assert make_id("psf/requests", "commit", "ABC123") == "psf/requests#commit:abc123"


def test_function_key_keeps_path_and_qualified_name():
    assert (
        make_id("psf/requests", "fn", "src/requests/sessions.py::Session.rebuild_auth")
        == "psf/requests#fn:src/requests/sessions.py::Session.rebuild_auth"
    )


def test_repo_id_is_bare_repo():
    assert repo_id("psf/requests") == "psf/requests"


@pytest.mark.parametrize(
    "bad", ["requests", "psf/", "/requests", "psf/requests/extra", "", "psf requests"]
)
def test_bad_repo_rejected(bad):
    with pytest.raises(ValueError):
        normalize_repo(bad)


def test_unknown_kind_rejected():
    with pytest.raises(ValueError, match="unknown id kind"):
        make_id("psf/requests", "pullrequest", 1)


@pytest.mark.parametrize("bad_key", ["", "   ", "a\nb", "a\tb"])
def test_bad_key_rejected(bad_key):
    with pytest.raises(ValueError):
        make_id("psf/requests", "file", bad_key)


def test_decision_id_is_stable_and_prefixed():
    a = decision_id("psf/requests", "psf/requests#pr:5797", "v1", 0)
    assert a == decision_id("psf/requests", "psf/requests#pr:5797", "v1", 0)
    assert a.startswith("psf/requests#dec:")
    assert len(a.split(":", 1)[1]) == 16


def test_decision_id_changes_with_source_prompt_and_index():
    base = decision_id("psf/requests", "psf/requests#pr:5797", "v1", 0)
    assert base != decision_id("psf/requests", "psf/requests#pr:5798", "v1", 0)
    assert base != decision_id("psf/requests", "psf/requests#pr:5797", "v2", 0)
    assert base != decision_id("psf/requests", "psf/requests#pr:5797", "v1", 1)


def test_decision_index_must_be_non_negative():
    with pytest.raises(ValueError):
        decision_id("psf/requests", "psf/requests#pr:5797", "v1", -1)
