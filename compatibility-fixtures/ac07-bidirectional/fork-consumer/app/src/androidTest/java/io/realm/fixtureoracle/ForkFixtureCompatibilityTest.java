package io.realm.fixtureoracle;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import android.content.Context;
import androidx.test.platform.app.InstrumentationRegistry;
import io.realm.DynamicRealm;
import io.realm.Realm;
import io.realm.RealmConfiguration;
import io.realm.RealmMigration;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.Test;

/** AC-07 fork half: read an immutable official copy, mutate only a working copy, and reopen it. */
public final class ForkFixtureCompatibilityTest {
    private static final String INPUT_DIRECTORY = "ac07-original";
    private static final String WORKING_DIRECTORY = "ac07-working";
    private static final String REPORT_DIRECTORY = "ac07-results";
    private static final String PLAIN = "official-10.19.0-plain.realm";
    private static final String ENCRYPTED = "official-10.19.0-encrypted.realm";

    @Test
    public void openOfficialCopiesWithForkThenCrudAndReopenWithoutMigration() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        Realm.init(context);
        byte[] key = readFixtureKey(context);
        File input = new File(context.getFilesDir(), INPUT_DIRECTORY);
        assertTrue("Host harness must import immutable official fixtures before this test", input.isDirectory());

        String plainSourceHash = sha256File(new File(input, PLAIN));
        String encryptedSourceHash = sha256File(new File(input, ENCRYPTED));
        CaseResult plain = exerciseFixture(context, input, PLAIN, null);
        CaseResult encrypted = exerciseFixture(context, input, ENCRYPTED, key);
        assertEquals("Fork test must never alter imported plain oracle", plainSourceHash, sha256File(new File(input, PLAIN)));
        assertEquals("Fork test must never alter imported encrypted oracle", encryptedSourceHash, sha256File(new File(input, ENCRYPTED)));
        writeReport(context, plainSourceHash, encryptedSourceHash, plain, encrypted);
    }

    /**
     * AC-07 failure isolation: verifies current fork encryption independently
     * of the historical official fixture format.
     */
    @Test
    public void createAndReopenFreshEncryptedRealm() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        Realm.init(context);
        byte[] key = readFixtureKey(context);
        File directory = new File(context.getFilesDir(), "ac07-fresh-encrypted");
        if (!directory.exists() && !directory.mkdirs()) throw new IOException("Cannot create " + directory);
        RealmConfiguration configuration = new RealmConfiguration.Builder()
            .directory(directory)
            .name("fork-fresh-encrypted.realm")
            .schemaVersion(7)
            .encryptionKey(key)
            .build();
        Realm.deleteRealm(configuration);
        Realm realm = Realm.getInstance(configuration);
        try {
            realm.executeTransaction(transaction -> {
                FixturePerson person = transaction.createObject(FixturePerson.class, 200L);
                person.setName("Fork fresh encrypted");
                person.setActive(true);
                person.setCreatedAt(new Date(1700000003000L));
                person.setPayload(new byte[] {99, 98, 97, 96});
            });
        } finally {
            realm.close();
        }
        Realm reopened = Realm.getInstance(configuration);
        try {
            FixturePerson person = reopened.where(FixturePerson.class).equalTo("id", 200L).findFirst();
            assertNotNull(person);
            assertEquals("Fork fresh encrypted", person.getName());
            assertTrue(person.isActive());
            assertEquals(1700000003000L, person.getCreatedAt().getTime());
            assertArrayEquals(new byte[] {99, 98, 97, 96}, person.getPayload());
        } finally {
            reopened.close();
        }
    }

    private static CaseResult exerciseFixture(Context context, File input, String name, byte[] key) throws Exception {
        File workingDirectory = new File(context.getFilesDir(), WORKING_DIRECTORY);
        if (!workingDirectory.exists() && !workingDirectory.mkdirs()) throw new IOException("Cannot create " + workingDirectory);
        File original = new File(input, name);
        assertTrue("Missing imported official fixture " + original, original.isFile());
        File working = new File(workingDirectory, name);
        copy(original, working);

        AtomicInteger migrationCalls = new AtomicInteger();
        RealmConfiguration.Builder builder = new RealmConfiguration.Builder()
            .directory(workingDirectory)
            .name(name)
            .schemaVersion(7)
            .migration(new CountingMigration(migrationCalls));
        if (key != null) builder.encryptionKey(key);
        RealmConfiguration configuration = builder.build();
        Realm realm = Realm.getInstance(configuration);
        try {
            assertEquals("Same schema must not invoke a migration", 0, migrationCalls.get());
            assertOfficialGolden(realm);
            realm.executeTransaction(transaction -> {
                FixturePerson ada = transaction.where(FixturePerson.class).equalTo("id", 101L).findFirst();
                assertNotNull(ada);
                ada.setName("Ada Lovelace");
                FixturePerson grace = transaction.where(FixturePerson.class).equalTo("id", 100L).findFirst();
                assertNotNull(grace);
                FixturePerson katherine = transaction.createObject(FixturePerson.class, 102L);
                katherine.setName("Katherine");
                katherine.setActive(true);
                katherine.setCreatedAt(new Date(1700000002000L));
                katherine.setPayload(new byte[] {42, 43, 44, 45});
                katherine.setParent(grace);
            });
            assertForkCrudResult(realm);
        } finally {
            realm.close();
        }

        Realm reopened = Realm.getInstance(configuration);
        try {
            assertEquals("Reopen must not invoke a migration", 0, migrationCalls.get());
            assertForkCrudResult(reopened);
        } finally {
            reopened.close();
        }

        boolean wrongKeyRejected = false;
        byte[] wrongKey = new byte[64];
        for (int index = 0; index < wrongKey.length; index++) wrongKey[index] = (byte) 0x5a;
        if (key != null) {
            RealmConfiguration wrongKeyConfiguration = new RealmConfiguration.Builder()
                .directory(workingDirectory).name(name).schemaVersion(7).encryptionKey(wrongKey).build();
            try {
                Realm wrongKeyRealm = Realm.getInstance(wrongKeyConfiguration);
                try {
                    // Opening with the wrong key must not become a semantic read success.
                    wrongKeyRealm.where(FixturePerson.class).count();
                } finally {
                    wrongKeyRealm.close();
                }
            } catch (RuntimeException expected) {
                wrongKeyRejected = true;
            }
            assertTrue("Wrong encryption key must be rejected", wrongKeyRejected);
        }
        return new CaseResult(sha256File(working), migrationCalls.get(), wrongKeyRejected);
    }

    private static void assertOfficialGolden(Realm realm) {
        assertEquals(2, realm.where(FixturePerson.class).count());
        FixturePerson grace = realm.where(FixturePerson.class).equalTo("id", 100L).findFirst();
        FixturePerson ada = realm.where(FixturePerson.class).equalTo("id", 101L).findFirst();
        assertNotNull(grace);
        assertNotNull(ada);
        assertEquals("Grace", grace.getName());
        assertTrue(grace.isActive());
        assertEquals(1700000000000L, grace.getCreatedAt().getTime());
        assertArrayEquals(new byte[] {1, 2, 3, 4}, grace.getPayload());
        assertEquals("Ada", ada.getName());
        assertFalse(ada.isActive());
        assertEquals(1700000001000L, ada.getCreatedAt().getTime());
        assertArrayEquals(new byte[] {10, 11, 12, 13}, ada.getPayload());
        assertNotNull(ada.getParent());
        assertEquals(100L, ada.getParent().getId());
    }

    private static void assertForkCrudResult(Realm realm) {
        assertEquals(3, realm.where(FixturePerson.class).count());
        FixturePerson ada = realm.where(FixturePerson.class).equalTo("id", 101L).findFirst();
        FixturePerson katherine = realm.where(FixturePerson.class).equalTo("id", 102L).findFirst();
        assertNotNull(ada);
        assertNotNull(katherine);
        assertEquals("Ada Lovelace", ada.getName());
        assertEquals("Katherine", katherine.getName());
        assertTrue(katherine.isActive());
        assertEquals(1700000002000L, katherine.getCreatedAt().getTime());
        assertArrayEquals(new byte[] {42, 43, 44, 45}, katherine.getPayload());
        assertNotNull(katherine.getParent());
        assertEquals(100L, katherine.getParent().getId());
    }

    private static byte[] readFixtureKey(Context context) throws IOException {
        File keyFile = new File(context.getFilesDir(), INPUT_DIRECTORY + "/fixture-key.hex");
        String hex = new String(readAll(keyFile), StandardCharsets.UTF_8).trim();
        if (!hex.matches("[0-9a-fA-F]{128}")) throw new IOException("Imported fixture key must contain 128 hex characters");
        byte[] key = new byte[64];
        for (int index = 0; index < key.length; index++) key[index] = (byte) Integer.parseInt(hex.substring(index * 2, index * 2 + 2), 16);
        return key;
    }

    private static void writeReport(Context context, String plainSourceHash, String encryptedSourceHash, CaseResult plain, CaseResult encrypted) throws Exception {
        File outputDirectory = new File(context.getFilesDir(), REPORT_DIRECTORY);
        if (!outputDirectory.exists() && !outputDirectory.mkdirs()) throw new IOException("Cannot create " + outputDirectory);
        String json = String.format(Locale.ROOT,
            "{\n  \"plain\": {\"source_sha256\": \"%s\", \"working_sha256\": \"%s\", \"migration_callbacks\": %d},\n" +
            "  \"encrypted\": {\"source_sha256\": \"%s\", \"working_sha256\": \"%s\", \"migration_callbacks\": %d, \"wrong_key_rejected\": %s}\n}\n",
            plainSourceHash, plain.workingHash, plain.migrationCalls, encryptedSourceHash, encrypted.workingHash,
            encrypted.migrationCalls, Boolean.toString(encrypted.wrongKeyRejected));
        try (FileOutputStream stream = new FileOutputStream(new File(outputDirectory, "fork-report.json"))) {
            stream.write(json.getBytes(StandardCharsets.UTF_8));
        }
    }

    private static void copy(File source, File destination) throws IOException {
        try (FileInputStream input = new FileInputStream(source); FileOutputStream output = new FileOutputStream(destination)) {
            byte[] buffer = new byte[8192];
            for (int count; (count = input.read(buffer)) != -1;) output.write(buffer, 0, count);
        }
    }

    private static byte[] readAll(File file) throws IOException {
        try (FileInputStream input = new FileInputStream(file); java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream()) {
            byte[] buffer = new byte[512];
            for (int count; (count = input.read(buffer)) != -1;) output.write(buffer, 0, count);
            return output.toByteArray();
        }
    }

    private static String sha256File(File file) throws Exception {
        try (FileInputStream stream = new FileInputStream(file)) {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[8192];
            for (int count; (count = stream.read(buffer)) != -1;) digest.update(buffer, 0, count);
            return hex(digest.digest());
        }
    }

    private static String hex(byte[] input) {
        StringBuilder result = new StringBuilder(input.length * 2);
        for (byte value : input) result.append(String.format(Locale.ROOT, "%02x", value & 0xff));
        return result.toString();
    }

    private static final class CountingMigration implements RealmMigration {
        private final AtomicInteger calls;
        CountingMigration(AtomicInteger calls) { this.calls = calls; }
        @Override public void migrate(DynamicRealm realm, long oldVersion, long newVersion) { calls.incrementAndGet(); }
    }

    private static final class CaseResult {
        final String workingHash;
        final int migrationCalls;
        final boolean wrongKeyRejected;
        CaseResult(String workingHash, int migrationCalls, boolean wrongKeyRejected) {
            this.workingHash = workingHash;
            this.migrationCalls = migrationCalls;
            this.wrongKeyRejected = wrongKeyRejected;
        }
    }
}
