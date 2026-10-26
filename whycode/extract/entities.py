"""Code entities (File, Class, Function, ConfigKey) from Python source, parsed with tree-sitter."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


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

    @property
    def entities(self) -> list[CodeEntity]:
        return [self.file, *self.classes, *self.functions, *self.config_keys]
