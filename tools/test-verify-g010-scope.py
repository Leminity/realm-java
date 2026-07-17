#!/usr/bin/env python3
"""Small regression tests for the deterministic G010 scope verifier."""

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("scope", ROOT / "tools/verify-g010-scope.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

assert MODULE.is_product_source("realm/realm-library/src/main/java/io/realm/Realm.java")
assert MODULE.is_product_source("realm-transformer/src/main/kotlin/io/realm/transformer/RealmTransformer.kt")
assert not MODULE.is_product_source("compatibility-fixtures/ac08/app/src/main/java/Fake.java")
assert not MODULE.is_product_source("realm/realm-library/src/androidTest/java/io/realm/Fake.java")
assert not MODULE.is_product_source("realm/realm-library/src/main/cpp/generated-jni-headers/Fake.h")
assert MODULE.is_build_or_publication("mavencentral-publications.gradle")
assert not MODULE.is_build_or_publication("compatibility-fixtures/ac08/build.gradle")
assert MODULE.CORE_APPROVED_PATHS <= {
    "src/realm/alloc.hpp",
    "src/realm/alloc_slab.cpp",
    "src/realm/util/encrypted_file_mapping.cpp",
    "src/realm/util/encrypted_file_mapping.hpp",
    "src/realm/util/file.cpp",
    "src/realm/util/file.hpp",
    "src/realm/util/file_mapper.cpp",
    "src/realm/util/file_mapper.hpp",
    "test/test_alloc.cpp",
    "test/test_encrypted_file_mapping.cpp",
    "test/test_shared.cpp",
}
assert MODULE.CORE_EXPECTED_PATHS == MODULE.CORE_APPROVED_PATHS | {
    "src/external/s2/base/macros.h"
}
assert MODULE.RETIRED_PROCESSOR_PATHS <= set(MODULE.SOURCE_APPROVALS)
assert MODULE.CORE_TOOLCHAIN_PREREQUISITE == "b741862e7ca7cb1b81d276457989067b7737dc86"

with tempfile.TemporaryDirectory() as temporary:
    source = Path(temporary) / "fixture.gradle"
    source.write_text("// ossrh archival prose\nplugins { id 'java' }\n", encoding="utf-8")
    assert MODULE.code_lines(source) == [(2, "plugins { id 'java' }")]

assert MODULE.FORBIDDEN_EXECUTION.search("project.hasProperty('ossrhUsername')")
assert not MODULE.FORBIDDEN_RUNTIME.search("Realm Sync/ObjectServer is unsupported by this fork")
assert MODULE.FORBIDDEN_RUNTIME.search("https://static.realm.io/update")
assert MODULE.numstat_paths.__defaults__ == (False, ())

print("G010 scope verifier regression tests: PASS")
