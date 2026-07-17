#!/usr/bin/env python3
"""Regression checks for the deterministic G009/AC-09 verifier helpers."""

import hashlib
import importlib.util
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
assert MODULE.normalize_javap_output(
    "fixture.Sample",
    'Compiled from "Sample.kt"\npublic final class fixture.Sample {\n\n  public void value();\n}\n',
) == "public final class fixture.Sample {\n  public void value();\n}"

with tempfile.TemporaryDirectory() as temporary:
    archive = Path(temporary) / "artifact.jar"
    archive.write_bytes(b"fixture")
    assert MODULE.sha256(archive) == hashlib.sha256(b"fixture").hexdigest()

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
