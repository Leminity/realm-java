#!/usr/bin/env python3
"""Verify the atomic seven-artifact Local-only Maven publication contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET
import zipfile


EXPECTED = (
    {"stage": "1", "artifact": "realm-annotations", "extension": "jar", "edges": ()},
    {"stage": "2.1", "artifact": "realm-transformer", "extension": "jar", "edges": ("realm-annotations",)},
    {"stage": "2.2", "artifact": "realm-library-build-transformer", "extension": "jar", "edges": ()},
    {"stage": "3.1", "artifact": "realm-android-library", "extension": "aar", "edges": ("realm-annotations",)},
    {"stage": "3.2", "artifact": "realm-annotations-processor", "extension": "jar", "edges": ("realm-annotations",)},
    {"stage": "3.3", "artifact": "realm-android-kotlin-extensions", "extension": "aar", "edges": ("realm-android-library",)},
    {"stage": "4", "artifact": "realm-gradle-plugin", "extension": "jar", "edges": ("realm-transformer",)},
)

PLUGIN_INJECTIONS = (
    "realm-annotations",
    "realm-annotations-processor",
    "realm-android-library",
    "realm-android-kotlin-extensions",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(node: ET.Element, name: str) -> str | None:
    for child in node:
        if local_name(child.tag) == name:
            return child.text
    return None


def repository_path(raw: str) -> Path:
    parsed = urlparse(raw)
    if parsed.scheme not in ("", "file"):
        raise ValueError(f"fork repository must be a file URI, got: {raw}")
    return Path(unquote(parsed.path if parsed.scheme else raw)).resolve()


def module_edges(module: dict, group: str) -> set[str]:
    edges: set[str] = set()
    for variant in module.get("variants", []):
        for dependency in variant.get("dependencies", []):
            if dependency.get("group") == group:
                edges.add(dependency.get("module"))
    return edges


def inspect_coordinate(repository: Path, group: str, version: str, expected: dict) -> dict:
    artifact = expected["artifact"]
    base = repository.joinpath(*group.split("."), artifact, version)
    main = base / f"{artifact}-{version}.{expected['extension']}"
    pom = base / f"{artifact}-{version}.pom"
    module = base / f"{artifact}-{version}.module"
    errors: list[str] = []

    for path in (main, pom, module):
        if not path.is_file():
            errors.append(f"missing published file: {path}")

    pom_edges: set[str] = set()
    io_realm_dependencies: list[str] = []
    if pom.is_file():
        root = ET.parse(pom).getroot()
        actual = {
            "group": child_text(root, "groupId"),
            "artifact": child_text(root, "artifactId"),
            "version": child_text(root, "version"),
        }
        wanted = {"group": group, "artifact": artifact, "version": version}
        if actual != wanted:
            errors.append(f"POM identity {actual} != {wanted}")
        for node in root.iter():
            if local_name(node.tag) != "dependency":
                continue
            dep_group = child_text(node, "groupId")
            dep_artifact = child_text(node, "artifactId")
            dep_version = child_text(node, "version")
            if dep_group == group:
                pom_edges.add(dep_artifact or "")
                if dep_version != version:
                    errors.append(
                        f"fork POM dependency {dep_group}:{dep_artifact} uses {dep_version}, expected {version}"
                    )
            if dep_group == "io.realm":
                io_realm_dependencies.append(f"{dep_group}:{dep_artifact}:{dep_version}")
        if io_realm_dependencies:
            errors.append(f"io.realm POM leakage: {sorted(io_realm_dependencies)}")

    expected_edges = set(expected["edges"])
    if pom_edges != expected_edges:
        errors.append(f"POM fork edges {sorted(pom_edges)} != {sorted(expected_edges)}")

    metadata_edges: set[str] = set()
    if module.is_file():
        metadata = json.loads(module.read_text())
        component = metadata.get("component", {})
        actual_component = (
            component.get("group"),
            component.get("module"),
            component.get("version"),
        )
        wanted_component = (group, artifact, version)
        if actual_component != wanted_component:
            errors.append(f"module component {actual_component} != {wanted_component}")
        metadata_edges = module_edges(metadata, group)
        if metadata_edges != expected_edges:
            errors.append(
                f"module fork edges {sorted(metadata_edges)} != {sorted(expected_edges)}"
            )
        if any(
            dependency.get("group") == "io.realm"
            for variant in metadata.get("variants", [])
            for dependency in variant.get("dependencies", [])
        ):
            errors.append("io.realm Gradle module metadata leakage")

    if main.is_file():
        try:
            with zipfile.ZipFile(main) as archive:
                if not archive.namelist():
                    errors.append("published archive is empty")
        except zipfile.BadZipFile:
            errors.append("published main artifact is not a ZIP/JAR/AAR")

    files = []
    if base.is_dir():
        for path in sorted(p for p in base.iterdir() if p.is_file()):
            files.append({"name": path.name, "size": path.stat().st_size, "sha256": sha256(path)})

    return {
        "stage": expected["stage"],
        "coordinate": f"{group}:{artifact}:{version}",
        "path": str(base),
        "main_artifact": str(main),
        "pom": str(pom),
        "module_metadata": str(module),
        "expected_edges": sorted(expected_edges),
        "pom_edges": sorted(pom_edges),
        "module_edges": sorted(metadata_edges),
        "files": files,
        "errors": errors,
        "pass": not errors,
    }


def inspect_plugin_injections(repository: Path, group: str, version: str) -> dict:
    plugin = repository.joinpath(
        *group.split("."),
        "realm-gradle-plugin",
        version,
        f"realm-gradle-plugin-{version}.jar",
    )
    errors: list[str] = []
    matches: dict[str, bool] = {}
    if not plugin.is_file():
        errors.append(f"missing plugin artifact: {plugin}")
    else:
        with zipfile.ZipFile(plugin) as archive:
            data = b"".join(archive.read(name) for name in archive.namelist() if not name.endswith("/"))
        for value in (group, version, *PLUGIN_INJECTIONS):
            found = value.encode() in data
            matches[value] = found
            if not found:
                errors.append(f"plugin artifact does not contain required fork injection marker: {value}")
    return {"path": str(plugin), "matches": matches, "errors": errors, "pass": not errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repository = repository_path(args.repository)
    coordinates = [inspect_coordinate(repository, args.group, args.version, item) for item in EXPECTED]
    group_root = repository.joinpath(*args.group.split("."))
    object_server_paths = sorted(
        str(path) for path in group_root.rglob("*object-server*") if path.exists()
    ) if group_root.exists() else []
    plugin_injections = inspect_plugin_injections(repository, args.group, args.version)
    errors = []
    if object_server_paths:
        errors.append(f"object-server artifacts were published: {object_server_paths}")
    if not all(item["pass"] for item in coordinates):
        errors.append("one or more coordinates failed validation")
    if not plugin_injections["pass"]:
        errors.append("plugin injection markers failed validation")

    payload = {
        "schema_version": 1,
        "repository": str(repository),
        "group": args.group,
        "version": args.version,
        "stage_order": [item["stage"] for item in EXPECTED],
        "coordinates": coordinates,
        "plugin_injections": plugin_injections,
        "object_server_paths": object_server_paths,
        "errors": errors,
        "pass": not errors,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
