import pytest

from whycode.extract.entities import (
    ParsedFile,
    PathOutsideRepoError,
    parse_source,
)
from whycode.ids import make_id

REPO = "psf/requests"

# Line numbers below are asserted exactly; keep this text unchanged or update the tests.
SAMPLE = '''\
"""Adapters."""
import os
from x import IMPORTED_CONST

DEFAULT_RETRIES = 3
DEFAULT_POOLSIZE: int = 10
lowercase_value = 1
T = TypeVar("T")


def top(a, b=2):
    return a


class HTTPAdapter(BaseAdapter):
    LIMIT = 5

    def __init__(self, pool=DEFAULT_POOLSIZE, max_retries=DEFAULT_RETRIES):
        self.x = 1

    @property
    def name(self):
        return "n"

    @name.setter
    def name(self, value):
        pass

    class Inner:
        def deep(self):
            def helper():
                pass
            return helper


async def fetch(url, timeout: float = 5.0):
    pass


@decorator(
    "multi",
)
def decorated(
    x,
    y,
):
    return x
'''


@pytest.fixture(scope="module")
def sample() -> ParsedFile:
    return parse_source(SAMPLE, "src/requests/adapters.py", REPO)


def by_qual(items):
    return {e.qualified_name: e for e in items}


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


# ---------- functions and classes ----------


def test_module_level_function(sample):
    fn = by_qual(sample.functions)["top"]
    assert fn.id == "psf/requests#fn:src/requests/adapters.py::top"
    assert fn.name == "top"
    assert (fn.start_line, fn.end_line, fn.def_line) == (11, 12, 11)
    assert fn.parent_id == sample.file.id == fn.file_id
    assert not fn.is_method and not fn.is_async


def test_class_with_methods(sample):
    cls = by_qual(sample.classes)["HTTPAdapter"]
    assert cls.id == "psf/requests#class:src/requests/adapters.py::HTTPAdapter"
    assert (cls.start_line, cls.end_line) == (15, 33)
    assert cls.parent_id == sample.file.id
    init = by_qual(sample.functions)["HTTPAdapter.__init__"]
    # Matches the schema example "<repo>#fn:<path>::Session.rebuild_auth".
    assert init.id == "psf/requests#fn:src/requests/adapters.py::HTTPAdapter.__init__"
    assert init.parent_id == cls.id and init.is_method
    assert (init.start_line, init.end_line) == (18, 19)


def test_nested_class_and_function_in_nested_class(sample):
    inner = by_qual(sample.classes)["HTTPAdapter.Inner"]
    outer = by_qual(sample.classes)["HTTPAdapter"]
    assert inner.parent_id == outer.id
    assert (inner.start_line, inner.end_line) == (29, 33)
    deep = by_qual(sample.functions)["HTTPAdapter.Inner.deep"]
    assert deep.parent_id == inner.id and deep.is_method


def test_nested_function(sample):
    deep = by_qual(sample.functions)["HTTPAdapter.Inner.deep"]
    helper = by_qual(sample.functions)["HTTPAdapter.Inner.deep.helper"]
    assert helper.name == "helper"
    assert helper.parent_id == deep.id
    assert not helper.is_method
    assert (helper.start_line, helper.end_line) == (31, 32)


def test_async_function(sample):
    fn = by_qual(sample.functions)["fetch"]
    assert fn.is_async
    assert (fn.start_line, fn.end_line) == (36, 37)


def test_decorated_multiline_function_includes_decorators_in_range(sample):
    fn = by_qual(sample.functions)["decorated"]
    assert fn.decorators == ('decorator( "multi", )',)
    assert fn.start_line == 40  # first decorator line
    assert fn.def_line == 43
    assert fn.end_line == 47


def test_property_getter_and_setter_get_distinct_ids(sample):
    names = [f for f in sample.functions if f.qualified_name == "HTTPAdapter.name"]
    assert [f.decorators for f in names] == [("property",), ("name.setter",)]
    assert names[0].id.endswith("::HTTPAdapter.name")
    assert names[1].id.endswith("::HTTPAdapter.name~2")
    assert (names[0].start_line, names[0].def_line, names[0].end_line) == (21, 22, 23)
    assert (names[1].start_line, names[1].end_line) == (25, 27)


def test_methods_not_confused_with_module_functions():
    src = "def run():\n    pass\n\nclass A:\n    def run(self):\n        pass\n"
    parsed = parse_source(src, "m.py", REPO)
    fns = by_qual(parsed.functions)
    assert set(fns) == {"run", "A.run"}
    assert fns["run"].id != fns["A.run"].id
    assert not fns["run"].is_method and fns["A.run"].is_method


def test_decorated_class():
    parsed = parse_source("@dataclass\nclass C:\n    x: int = 1\n", "m.py", REPO)
    (cls,) = parsed.classes
    assert (cls.start_line, cls.def_line, cls.end_line, cls.decorators) == (1, 2, 3, ("dataclass",))


def test_crlf_and_trailing_blank_lines_do_not_shift_lines():
    parsed = parse_source(b"def f():\r\n    return 1\r\n\r\n\r\n", "m.py", REPO)
    (fn,) = parsed.functions
    assert (fn.start_line, fn.end_line) == (1, 2)


def test_lambdas_are_not_functions():
    parsed = parse_source("f = lambda x=1: x\n", "m.py", REPO)
    assert parsed.functions == () and parsed.config_keys == ()


# ---------- config keys ----------


def test_uppercase_module_constant(sample):
    cfg = by_qual(sample.config_keys)["DEFAULT_RETRIES"]
    assert cfg.id == "psf/requests#cfg:src/requests/adapters.py::DEFAULT_RETRIES"
    assert cfg.source == "module_constant"
    assert cfg.value == "3"
    assert (cfg.start_line, cfg.end_line) == (5, 5)
    assert cfg.parent_id == sample.file.id


def test_annotated_constant(sample):
    cfg = by_qual(sample.config_keys)["DEFAULT_POOLSIZE"]
    assert cfg.value == "10" and cfg.start_line == 6


def test_multiline_constant_value_and_range():
    src = "SETTINGS = {\n    'a': 1,\n    'b': 2,\n}\n"
    (cfg,) = parse_source(src, "m.py", REPO).config_keys
    assert (cfg.start_line, cfg.end_line) == (1, 4)
    assert cfg.value.startswith("{") and cfg.value.endswith("}")


def test_redefined_constant_gets_ordinal_id():
    src = "try:\n    MODE = 'fast'\nexcept ImportError:\n    MODE = 'slow'\n"
    a, b = parse_source(src, "m.py", REPO).config_keys
    assert a.id.endswith("::MODE") and b.id.endswith("::MODE~2")
    assert a.qualified_name == b.qualified_name == "MODE"
