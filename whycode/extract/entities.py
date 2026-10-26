"""Code entities (File, Class, Function, ConfigKey) from Python source, parsed with tree-sitter."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Literal

import tree_sitter_python
from pydantic import BaseModel, ConfigDict
from tree_sitter import Language, Node, Parser

from whycode.ids import make_id, normalize_repo

_WS_RE = re.compile(r"\s+")


class EntityExtractionError(Exception):
    """A file could not be parsed for an expected reason (path, type, size or encoding)."""


class PathOutsideRepoError(EntityExtractionError, ValueError):
    """The requested path resolves outside the repository root."""


class _Entity(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    repo: str
    name: str
    file_path: str


class FileEntity(_Entity):
    kind: Literal["File"] = "File"
    line_count: int


class _SpanEntity(_Entity):
    qualified_name: str
    file_id: str
    parent_id: str  # the file, or the enclosing class or function
    start_line: int
    end_line: int


class ClassEntity(_SpanEntity):
    kind: Literal["Class"] = "Class"
    def_line: int
    decorators: tuple[str, ...] = ()


class FunctionEntity(_SpanEntity):
    kind: Literal["Function"] = "Function"
    def_line: int
    decorators: tuple[str, ...] = ()
    is_async: bool = False
    is_method: bool = False  # defined directly in a class body


class ConfigKeyEntity(_SpanEntity):
    kind: Literal["ConfigKey"] = "ConfigKey"
    source: Literal["module_constant", "default_argument"]
    value: str


CodeEntity = FileEntity | ClassEntity | FunctionEntity | ConfigKeyEntity


class ParsedFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: FileEntity
    classes: tuple[ClassEntity, ...] = ()
    functions: tuple[FunctionEntity, ...] = ()
    config_keys: tuple[ConfigKeyEntity, ...] = ()
    has_syntax_errors: bool = False

    @property
    def entities(self) -> list[CodeEntity]:
        return [self.file, *self.classes, *self.functions, *self.config_keys]


@lru_cache(maxsize=1)
def _language() -> Language:
    return Language(tree_sitter_python.language())


# ---------- source -> entities ----------


def parse_source(source: bytes | str, path: str, repo: str) -> ParsedFile:
    """Extract entities from one file's source. `path` is the repo-relative path used in ids."""
    rel = _normalize_rel_path(path)
    repo = normalize_repo(repo)
    text = source if isinstance(source, str) else source.decode("utf-8")
    data = text.encode("utf-8")
    tree = Parser(_language()).parse(data)
    return _Extractor(repo, rel, _line_count(text)).run(tree.root_node)


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8") if node is not None and node.text is not None else ""


def _start_line(node: Node) -> int:
    return node.start_point.row + 1


def _end_line(node: Node) -> int:
    row, col = node.end_point
    # A span ending at column 0 stops before that line begins.
    if col == 0 and row > node.start_point.row:
        return row
    return row + 1


@dataclass(frozen=True)
class _Scope:
    kind: Literal["file", "class", "function"]
    entity_id: str
    qual: str  # dotted name, "" for the file


@dataclass
class _Extractor:
    repo: str
    path: str
    line_count: int
    file_id: str = ""
    classes: list[ClassEntity] = field(default_factory=list)
    functions: list[FunctionEntity] = field(default_factory=list)

    def run(self, root: Node) -> ParsedFile:
        self.file_id = file_id = make_id(self.repo, "file", self.path)
        file_scope = _Scope("file", file_id, "")
        # Iterative walk: deeply nested expressions must not hit Python's recursion limit.
        stack: list[tuple[Node, _Scope]] = [(root, file_scope)]
        while stack:
            node, scope = stack.pop()
            child_scope = self._visit(node, scope)
            stack.extend((c, child_scope) for c in reversed(node.children))
        return ParsedFile(
            file=FileEntity(
                id=file_id,
                repo=self.repo,
                name=PurePosixPath(self.path).name,
                file_path=self.path,
                line_count=self.line_count,
            ),
            classes=tuple(self.classes),
            functions=tuple(self.functions),
            has_syntax_errors=root.has_error,
        )

    def _visit(self, node: Node, scope: _Scope) -> _Scope:
        """Record the entity `node` defines, if any, and return the scope for its children."""
        if node.type == "class_definition":
            return self._definition(node, scope, "class")
        if node.type == "function_definition":
            return self._definition(node, scope, "function")
        return scope

    def _definition(self, node: Node, scope: _Scope, kind: Literal["class", "function"]) -> _Scope:
        name = _text(node.child_by_field_name("name"))
        if not name:  # recovered from a syntax error without a name: nothing to identify
            return scope
        span = node
        decorators: tuple[str, ...] = ()
        if node.parent is not None and node.parent.type == "decorated_definition":
            span = node.parent
            decorators = tuple(
                _WS_RE.sub(" ", _text(d)).lstrip("@ ")
                for d in span.children
                if d.type == "decorator"
            )
        qual = f"{scope.qual}.{name}" if scope.qual else name
        entity_id = make_id(self.repo, "class" if kind == "class" else "fn", f"{self.path}::{qual}")
        common = dict(
            id=entity_id,
            repo=self.repo,
            name=name,
            file_path=self.path,
            qualified_name=qual,
            file_id=self.file_id,
            parent_id=scope.entity_id,
            start_line=_start_line(span),
            end_line=_end_line(span),
            def_line=_start_line(node),
            decorators=decorators,
        )
        if kind == "class":
            self.classes.append(ClassEntity(**common))
        else:
            self.functions.append(
                FunctionEntity(
                    **common,
                    is_async=any(c.type == "async" for c in node.children),
                    is_method=scope.kind == "class",
                )
            )
        return _Scope(kind, entity_id, qual)


# ---------- files and repositories ----------


def _normalize_rel_path(path: str) -> str:
    """Validate a repo-relative path and return it with "/" separators."""
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if not parts or parts[0] == "/" or re.match(r"^[A-Za-z]:", parts[0]) or ".." in parts:
        raise PathOutsideRepoError(f"not a repository-relative path: {path!r}")
    cleaned = [p for p in parts if p != "."]
    if not cleaned:
        raise PathOutsideRepoError(f"not a repository-relative path: {path!r}")
    return "/".join(cleaned)
