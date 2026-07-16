# Fixture-oracle source locations

The following files were read from the exact upstream bootstrap checkout, without modifying it:

- `realm/realm-library/src/androidTest/assets/0841_pk_migration.realm` — tracked upstream migration fixture; SHA-256 recorded in `upstream-source-sha256.txt`.
- `realm/realm-library/src/androidTest/java/io/realm/RealmMigrationTests.java` — migration behavior assertions.
- `realm/realm-library/src/main/java/io/realm/RealmMigration.java` — public migration contract.
- `realm/realm-library/src/testUtils/java/io/realm/TestRealmConfigurationFactory.java` — configuration/encryption-key test helper.
- `README.md:221-240` — upstream connected instrumentation test command (`./gradlew connectedBaseDebugAndroidTest`).
