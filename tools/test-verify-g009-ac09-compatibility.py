#!/usr/bin/env python3
"""Regression checks for the deterministic G009/AC-09 verifier helpers."""

import hashlib
import importlib.util
import re
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ac09", ROOT / "tools/verify-g009-ac09-compatibility.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

assert MODULE.is_unsupported("io.realm.mongodb.sync.SyncConfiguration")
assert MODULE.is_unsupported("io.realm.internal.ObjectServerFacade")
assert not MODULE.is_unsupported("io.realm.RealmConfiguration")
assert MODULE.APPROVED_PUBLIC_CLASS_REMOVALS == {
    "realm-annotations-processor": {
        "io.realm.processor.RealmVersionChecker",
        "io.realm.processor.RealmVersionChecker$Companion",
    },
}
assert MODULE.APPROVED_COMPILER_SIGNATURE_ADDITIONS == {
    "io.realm.processor.Constants$RealmFieldType": {
        "signature": "  public static kotlin.enums.EnumEntries<io.realm.processor.Constants$RealmFieldType> getEntries();",
        "descriptor": "()Lkotlin/enums/EnumEntries;",
    },
}
assert MODULE.COMPILER_GENERATED_PUBLIC_CLASS_EXCLUSIONS == {
    "io.realm.processor.ClassMetaData$WhenMappings",
    "io.realm.processor.RealmProxyClassGenerator$WhenMappings",
    "io.realm.processor.Utils$WhenMappings",
}
processor_oracle = MODULE.load_oracle_signatures(ROOT)["realm-annotations-processor"]
assert not (set(processor_oracle) & MODULE.COMPILER_GENERATED_PUBLIC_CLASS_EXCLUSIONS)
assert MODULE.normalize_javap_output(
    "fixture.Sample",
    'Compiled from "Sample.kt"\npublic final class fixture.Sample {\n\n  public void value();\n}\n',
) == "public final class fixture.Sample {\n  public void value();\n}"

kotlin_extensions_build = (ROOT / "realm/kotlin-extensions/build.gradle").read_text(encoding="utf-8")
assert re.search(r"buildFeatures\s*\{\s*buildConfig\s*=\s*true\s*\}", kotlin_extensions_build)

with tempfile.TemporaryDirectory() as temporary:
    repository_root = Path(temporary) / "repository"
    archive = (
        repository_root
        / MODULE.FORK_GROUP_PATH
        / "realm-gradle-plugin"
        / MODULE.FORK_VERSION
        / f"realm-gradle-plugin-{MODULE.FORK_VERSION}.jar"
    )
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"fixture")
    assert MODULE.artifact_file(
        repository_root, "realm-gradle-plugin", MODULE.FORK_VERSION, ".jar"
    ) == archive
    assert MODULE.sha256(archive) == hashlib.sha256(b"fixture").hexdigest()

    public_api = Path(temporary) / "public-api.jar"
    # class_entries only reads the class-file header/access flags, so this
    # compact fixture distinguishes an ordinary public class from the exact
    # Kotlin enum-switch holder exclusions.
    public_class = b"\xca\xfe\xba\xbe\x00\x00\x00\x34\x00\x01\x00\x01"
    with zipfile.ZipFile(public_api, "w") as bundle:
        bundle.writestr("fixture/Visible.class", public_class)
        bundle.writestr("io/realm/processor/ClassMetaData$WhenMappings.class", public_class)
        bundle.writestr("io/realm/processor/RealmProxyClassGenerator$WhenMappings.class", public_class)
        bundle.writestr("io/realm/processor/Utils$WhenMappings.class", public_class)
    _, public_classes = MODULE.class_entries(public_api, Path(temporary) / "public-api")
    assert public_classes == {"fixture.Visible": 0x0001}

    clean_processor = Path(temporary) / "clean-processor.jar"
    with zipfile.ZipFile(clean_processor, "w") as bundle:
        bundle.writestr("io/realm/processor/RealmProcessor.class", b"processor")
    assert MODULE.verify_retired_processor_absence(clean_processor)["approved_removed_public_classes"] == [
        "io.realm.processor.RealmVersionChecker",
        "io.realm.processor.RealmVersionChecker$Companion",
    ]

    retired_processor = Path(temporary) / "retired-processor.jar"
    with zipfile.ZipFile(retired_processor, "w") as bundle:
        bundle.writestr("io/realm/processor/RealmProcessor.class", b"https://static.realm.io/update/java")
    try:
        MODULE.verify_retired_processor_absence(retired_processor)
    except MODULE.VerificationError:
        pass
    else:
        raise AssertionError("retired processor endpoint was accepted")

print("G009 AC-09 verifier regression tests: PASS")
