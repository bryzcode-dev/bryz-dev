from __future__ import annotations

from pathlib import PurePath, PurePosixPath, PureWindowsPath
from typing import Sequence

from projectos.adoption.host import HostFamily
from projectos.errors import ValidationError


class HostPathPolicy:
    def __init__(self, family: HostFamily):
        self.family = HostFamily(family)
        self.path_type = PureWindowsPath if family is HostFamily.WINDOWS else PurePosixPath

    def _path(self, value: str | PurePath) -> PurePath:
        return self.path_type(str(value))

    def is_absolute(self, value: str | PurePath) -> bool:
        return self._path(value).is_absolute()

    def normalize(self, value: str | PurePath) -> str:
        path = self._path(value)
        if not path.is_absolute():
            raise ValidationError("path must be absolute")
        anchor = path.anchor
        collapsed: list[str] = []
        for part in path.parts:
            if part == anchor or part in {"", "."}:
                continue
            if part == "..":
                if not collapsed:
                    raise ValidationError("path escapes its root")
                collapsed.pop()
                continue
            collapsed.append(part)
        normalized = str(self.path_type(anchor, *collapsed))
        return normalized.casefold() if self.family is HostFamily.WINDOWS else normalized

    def is_within(self, candidate: str | PurePath, root: str | PurePath) -> bool:
        try:
            candidate_path = self._path(self.normalize(candidate))
            root_path = self._path(self.normalize(root))
        except ValidationError:
            return False
        if candidate_path.anchor != root_path.anchor:
            return False
        root_parts = root_path.parts
        return candidate_path.parts[: len(root_parts)] == root_parts

    def assert_local_runtime(
        self, runtime: str | PurePath, shared_roots: Sequence[str | PurePath]
    ) -> None:
        normalized = self.normalize(runtime)
        for shared in shared_roots:
            if self.is_within(normalized, shared) or self.is_within(shared, normalized):
                raise ValidationError("runtime path must be local and outside shared roots")
