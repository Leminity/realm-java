#!/usr/bin/env python3
"""Verify the atomic seven-artifact Local-only Maven publication contract."""

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


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def child_text(node, name):
    for child in node:
        if local_name(child.tag) == name:
            return child.text
    return None


def repository_path(raw):
    parsed = urlparse(raw)
    if parsed.scheme not in ("", "file"):
        raise ValueError("fork repository must be a file URI, got: {}".format(raw))
    return Path(unquote(parsed.path if parsed.scheme else raw)).resolve()


def module_edges(module, group):
    edges = set()
    for variant in module.get("variants", []):
        for dependency in variant.get("dependencies", []):
            if dependency.get("group") == group:
                edges.add(dependency.get("module"))
    return edges


def inspect_coordinate(repository, group, version, expected):
    artifact = expected["artifact"]
    base = repository.joinpath(*group.split("."), artifact, version)
    main = base / "{}-{}.{}".format(artifact, version, expected["extension"])
    pom = base / "{}-{}.pom".format(artifact, version)
    module = base / "{}-{}.module".format(artifact, version)
    errors = []

    for path in (main, pom, module):
        if not path.is_file():
            errors.append("missing published file: {}".format(path))

    pom_edges = set()
    pom_packaging = None
    io_realm_dependencies = []
    if pom.is_file():
        root = ET.parse(str(pom)).getroot()
        pom_packaging = child_text(root, "packaging")
        actual = {
            "group": child_text(root, "groupId"),
            "artifact": child_text(root, "artifactId"),
            "version": child_text(root, "version"),
        }
        wanted = {"group": group, "artifact": artifact, "version": version}
        if actual != wanted:
            errors.append("POM identity {} != {}".format(actual, wanted))
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
                        "fork POM dependency {}:{} uses {}, expected {}".format(
                            dep_group, dep_artifact, dep_version, version
                        )
                    )
            if dep_group == "io.realm":
                io_realm_dependencies.append("{}:{}:{}".format(dep_group, dep_artifact, dep_version))
        if io_realm_dependencies:
            errors.append("io.realm POM leakage: {}".format(sorted(io_realm_dependencies)))
        if expected["extension"] == "aar" and pom_packaging != "aar":
            errors.append("AAR POM packaging {!r} != 'aar'".format(pom_packaging))

    expected_edges = set(expected["edges"])
    if pom_edges != expected_edges:
        errors.append("POM fork edges {} != {}".format(sorted(pom_edges), sorted(expected_edges)))

    metadata_edges = set()
    module_variant_usages = []
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
            errors.append("module component {} != {}".format(actual_component, wanted_component))
        metadata_edges = module_edges(metadata, group)
        if metadata_edges != expected_edges:
            errors.append(
                "module fork edges {} != {}".format(
                    sorted(metadata_edges), sorted(expected_edges)
                )
            )
        if any(
            dependency.get("group") == "io.realm"
            for variant in metadata.get("variants", [])
            for dependency in variant.get("dependencies", [])
        ):
            errors.append("io.realm Gradle module metadata leakage")
        module_variant_usages = sorted(
            {
                variant.get("attributes", {}).get("org.gradle.usage")
                for variant in metadata.get("variants", [])
                if variant.get("attributes", {}).get("org.gradle.usage")
            }
        )
        if expected["extension"] == "aar":
            required_usages = {"java-api", "java-runtime"}
            missing_usages = required_usages.difference(module_variant_usages)
            if missing_usages:
                errors.append(
                    "AAR module usages missing {}; published {}".format(
                        sorted(missing_usages), module_variant_usages
                    )
                )
            for usage in sorted(required_usages):
                usage_variants = [
                    variant
                    for variant in metadata.get("variants", [])
                    if variant.get("attributes", {}).get("org.gradle.usage") == usage
                ]
                if len(usage_variants) != 1:
                    errors.append(
                        "AAR module usage {} has {} variants, expected 1".format(
                            usage, len(usage_variants)
                        )
                    )
                    continue
                variant = usage_variants[0]
                if variant.get("attributes", {}).get("org.gradle.libraryelements") != "aar":
                    errors.append(
                        "AAR module usage {} does not advertise libraryelements=aar".format(usage)
                    )
                variant_edges = {
                    dependency.get("module")
                    for dependency in variant.get("dependencies", [])
                    if dependency.get("group") == group
                }
                if variant_edges != expected_edges:
                    errors.append(
                        "AAR module usage {} fork edges {} != {}".format(
                            usage, sorted(variant_edges), sorted(expected_edges)
                        )
                    )
                files = variant.get("files", [])
                if not any(
                    item.get("name") == main.name and item.get("url") == main.name
                    for item in files
                ):
                    errors.append("AAR module usage {} does not publish {}".format(usage, main.name))

    if main.is_file():
        try:
            with zipfile.ZipFile(str(main)) as archive:
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
        "coordinate": "{}:{}:{}".format(group, artifact, version),
        "path": str(base),
        "main_artifact": str(main),
        "pom": str(pom),
        "module_metadata": str(module),
        "expected_edges": sorted(expected_edges),
        "pom_edges": sorted(pom_edges),
        "pom_packaging": pom_packaging,
        "module_edges": sorted(metadata_edges),
        "module_variant_usages": module_variant_usages,
        "files": files,
        "errors": errors,
        "pass": not errors,
    }


def inspect_plugin_injections(repository, group, version):
    plugin = repository.joinpath(
        *group.split("."),
        "realm-gradle-plugin",
        version,
        "realm-gradle-plugin-{}.jar".format(version),
    )
    errors = []
    matches = {}
    if not plugin.is_file():
        errors.append("missing plugin artifact: {}".format(plugin))
    else:
        with zipfile.ZipFile(str(plugin)) as archive:
            data = b"".join(archive.read(name) for name in archive.namelist() if not name.endswith("/"))
        for value in (group, version, *PLUGIN_INJECTIONS):
            found = value.encode() in data
            matches[value] = found
            if not found:
                errors.append(
                    "plugin artifact does not contain required fork injection marker: {}".format(value)
                )
    return {"path": str(plugin), "matches": matches, "errors": errors, "pass": not errors}


def main():
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
        errors.append("object-server artifacts were published: {}".format(object_server_paths))
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
