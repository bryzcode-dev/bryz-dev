from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from projectos.errors import ValidationError


PARSER_VERSION = "1.0.0"
_SUPPORTED = (".lkml", ".lookml")


@dataclass(frozen=True)
class LookerAsset:
    asset_type: str
    name: str
    source_path: str
    content_sha256: str
    parser_version: str
    line: int

    @property
    def sort_key(self) -> tuple:
        return (self.asset_type, self.name, self.source_path, self.line)


@dataclass(frozen=True)
class LookerRelationship:
    relationship_type: str
    source_type: str
    source_name: str
    target_type: str
    target_name: str
    source_path: str
    line: int

    @property
    def sort_key(self) -> tuple:
        return (self.relationship_type, self.source_type, self.source_name, self.target_type, self.target_name, self.source_path, self.line)


@dataclass(frozen=True)
class LookerFinding:
    code: str
    subject: str
    source_path: str
    line: int

    @property
    def sort_key(self) -> tuple:
        return (self.code, self.subject, self.source_path, self.line)


@dataclass(frozen=True)
class ParsedLookerRepository:
    assets: tuple[LookerAsset, ...]
    relationships: tuple[LookerRelationship, ...]
    findings: tuple[LookerFinding, ...]


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _name(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1) if match else None


def _named_blocks(pattern: str, text: str):
    for header in re.finditer(pattern, text, re.MULTILINE):
        opening = header.end() - 1
        depth = 0
        quote = None
        escaped = False
        for index in range(opening, len(text)):
            character = text[index]
            if quote is not None:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == quote:
                    quote = None
                continue
            if character in {"\"", "'"}:
                quote = character
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    yield header, text[opening + 1:index], opening + 1
                    break


def parse_repository(root: Path) -> ParsedLookerRepository:
    selected = Path(root)
    if not selected.is_dir() or selected.is_symlink():
        raise ValidationError("Looker repository must be a non-symlink directory")
    assets: list[LookerAsset] = []
    edges: list[LookerRelationship] = []
    findings: list[LookerFinding] = []
    for path in sorted(selected.rglob("*")):
        if path.is_symlink():
            raise ValidationError("Looker repository cannot contain a symlink")
        if not path.is_file() or not path.name.endswith(_SUPPORTED):
            continue
        relative = path.relative_to(selected).as_posix()
        content = path.read_bytes()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            findings.append(LookerFinding("MALFORMED_LOOKML", relative, relative, 1))
            continue
        digest = hashlib.sha256(content).hexdigest()

        def asset(kind: str, name: str, offset: int) -> None:
            assets.append(LookerAsset(kind, name, relative, digest, PARSER_VERSION, _line(text, offset)))
            if kind != "file":
                edges.append(LookerRelationship("asset_file", kind, name, "file", relative, relative, _line(text, offset)))

        def edge(kind: str, source_type: str, source: str, target_type: str, target: str, offset: int) -> None:
            edges.append(LookerRelationship(kind, source_type, source, target_type, target, relative, _line(text, offset)))

        asset("file", relative, 0)

        if path.name == "manifest.lkml":
            project = _name(r"project_name:\s*[\"']?([A-Za-z0-9_-]+)", text) or selected.name
            asset("project", project, 0)
            for match in re.finditer(r"(?:local|remote)_dependency:\s*\{[^}]*project:\s*[\"']?([A-Za-z0-9_-]+)", text):
                edge("project_import", "project", project, "project", match.group(1), match.start())
        if path.name.endswith(".model.lkml"):
            model = path.name[: -len(".model.lkml")]
            asset("model", model, 0)
            for match in re.finditer(r"connection:\s*[\"']([^\"']+)", text):
                edge("model_connection", "model", model, "connection", match.group(1), match.start())
            for match in re.finditer(r"include:\s*[\"']([^\"']+)", text):
                edge("model_include", "model", model, "file", match.group(1), match.start())
            for match, body, body_offset in _named_blocks(r"explore:\s*([A-Za-z0-9_]+)\s*\{", text):
                explore = match.group(1)
                asset("explore", explore, match.start())
                target = _name(r"from:\s*([A-Za-z0-9_]+)", body) or explore
                edge("explore_view", "explore", explore, "view", target, match.start())
                extends = re.search(r"extends:\s*\[([^]]+)\]", body)
                if extends:
                    for parent in re.findall(r"[A-Za-z0-9_]+", extends.group(1)):
                        edge("explore_extends", "explore", explore, "explore", parent, body_offset + extends.start())
                persistence = re.search(r"persist_with:\s*[\"']?([A-Za-z0-9_]+)", body)
                if persistence:
                    edge("persist_with", "explore", explore, "datagroup", persistence.group(1), body_offset + persistence.start())
                for join in re.finditer(r"join:\s*([A-Za-z0-9_]+)", body):
                    edge("join_view", "explore", explore, "view", join.group(1), body_offset + join.start())
            for match, _body, _body_offset in _named_blocks(r"datagroup:\s*([A-Za-z0-9_]+)\s*\{", text):
                asset("datagroup", match.group(1), match.start())
        for match, body, body_offset in _named_blocks(r"view:\s*([A-Za-z0-9_]+)\s*\{", text):
            view = match.group(1)
            asset("view", view, match.start())
            extends = re.search(r"extends:\s*\[([^]]+)\]", body)
            if extends:
                for target in re.findall(r"[A-Za-z0-9_]+", extends.group(1)):
                    edge("view_extends", "view", view, "view", target, match.start() + extends.start())
        dashboard_matches = list(re.finditer(r"(?m)^\s*-?\s*dashboard:\s*([A-Za-z0-9_-]+)", text))
        for dashboard_index, match in enumerate(dashboard_matches):
            dashboard = match.group(1)
            asset("dashboard", dashboard, match.start())
            end = dashboard_matches[dashboard_index + 1].start() if dashboard_index + 1 < len(dashboard_matches) else len(text)
            body = text[match.end():end]
            model = _name(r"(?m)^\s*model:\s*([A-Za-z0-9_-]+)", body)
            explore = _name(r"(?m)^\s*explore:\s*([A-Za-z0-9_-]+)", body)
            if model:
                edge("dashboard_model", "dashboard", dashboard, "model", model, match.start())
            if explore:
                edge("dashboard_explore", "dashboard", dashboard, "explore", explore, match.start())
            elements = re.search(r"(?m)^\s*elements:\s*$", body)
            if elements:
                element_body = body[elements.end():]
                element_matches = list(re.finditer(r"(?m)^\s*-\s*name:\s*[\"']?([A-Za-z0-9_-]+)", element_body))
                for element_index, element_match in enumerate(element_matches):
                    element_name = f"{dashboard}:{element_match.group(1)}"
                    element_offset = match.end() + elements.end() + element_match.start()
                    element_end = element_matches[element_index + 1].start() if element_index + 1 < len(element_matches) else len(element_body)
                    definition = element_body[element_match.end():element_end]
                    element_model = _name(r"(?m)^\s*model:\s*([A-Za-z0-9_-]+)", definition) or model
                    element_explore = _name(r"(?m)^\s*explore:\s*([A-Za-z0-9_-]+)", definition) or explore
                    asset("dashboard_element", element_name, element_offset)
                    if element_model:
                        edge("dashboard_element_model", "dashboard_element", element_name, "model", element_model, element_offset)
                    if element_explore:
                        edge("dashboard_element_explore", "dashboard_element", element_name, "explore", element_explore, element_offset)
        if re.search(r"(?m)^\s*application:\s*", text):
            findings.append(LookerFinding("UNSUPPORTED_CONSTRUCT", "application", relative, 1))
        if text.count("{") != text.count("}"):
            findings.append(LookerFinding("MALFORMED_LOOKML", relative, relative, 1))

    counts: dict[tuple[str, str], int] = {}
    for item in assets:
        key = (item.asset_type, item.name)
        counts[key] = counts.get(key, 0) + 1
    for (kind, name), count in counts.items():
        if count > 1:
            findings.append(LookerFinding("DUPLICATE_ASSET", f"{kind}:{name}", "", 1))
    known = {(item.asset_type, item.name) for item in assets}
    for item in edges:
        if item.target_type in {"view", "model", "explore"} and (item.target_type, item.target_name) not in known:
            findings.append(LookerFinding("UNRESOLVED_REFERENCE", f"{item.target_type}:{item.target_name}", item.source_path, item.line))

    graph = {name: set() for kind, name in known if kind == "view"}
    for item in edges:
        if item.relationship_type == "view_extends" and item.source_name in graph and item.target_name in graph:
            graph[item.source_name].add(item.target_name)
    for start in sorted(graph):
        stack = [(start, (start,))]
        while stack:
            node, path = stack.pop()
            for target in sorted(graph[node]):
                if target == start:
                    findings.append(LookerFinding("REFERENCE_CYCLE", " -> ".join((*path, target)), "", 1))
                    stack.clear()
                    break
                if target not in path:
                    stack.append((target, (*path, target)))
    return ParsedLookerRepository(tuple(sorted(assets, key=lambda item: item.sort_key)), tuple(sorted(edges, key=lambda item: item.sort_key)), tuple(sorted(set(findings), key=lambda item: item.sort_key)))
