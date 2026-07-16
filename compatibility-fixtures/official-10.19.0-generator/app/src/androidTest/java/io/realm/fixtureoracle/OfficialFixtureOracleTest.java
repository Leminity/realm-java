package io.realm.fixtureoracle;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;

import android.content.Context;
import android.os.Build;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Date;
import java.util.Locale;
import io.realm.Realm;
import io.realm.RealmConfiguration;
import org.junit.Test;

public final class OfficialFixtureOracleTest {
    private static final String REALM_VERSION = "10.19.0";
    private static final String OFFICIAL_MANIFEST_SHA256 = "255be75f1dca64e2cc94574ced12c5acaa2bb749f8c7a3998056631f08c203a1";

    @Test
    public void generatePlainAndEncryptedFixturesAndVerifyWithOfficialReader() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        Realm.init(context);
        byte[] key = parseFixtureKey(BuildConfig.FIXTURE_KEY_HEX);
        File output = new File(context.getFilesDir(), "official-10.19.0-oracle");
        if (!output.exists() && !output.mkdirs()) throw new IOException("Cannot create " + output);

        File plain = generateFixture(output, "official-10.19.0-plain.realm", null);
        File encrypted = generateFixture(output, "official-10.19.0-encrypted.realm", key);
        verifySemanticRead(output, "official-10.19.0-plain.realm", null);
        verifySemanticRead(output, "official-10.19.0-encrypted.realm", key);
        writeManifest(InstrumentationRegistry.getInstrumentation().getContext(), output, plain, encrypted, key);
    }

    private static File generateFixture(File directory, String name, byte[] key) {
        RealmConfiguration.Builder builder = new RealmConfiguration.Builder().directory(directory).name(name).schemaVersion(7);
        if (key != null) builder.encryptionKey(key);
        RealmConfiguration configuration = builder.build();
        Realm.deleteRealm(configuration);
        Realm realm = Realm.getInstance(configuration);
        try {
            realm.executeTransaction(transaction -> {
                FixturePerson grace = transaction.createObject(FixturePerson.class, 100L);
                grace.setName("Grace");
                grace.setActive(true);
                grace.setCreatedAt(new Date(1700000000000L));
                grace.setPayload(new byte[] {1, 2, 3, 4});
                FixturePerson ada = transaction.createObject(FixturePerson.class, 101L);
                ada.setName("Ada");
                ada.setActive(false);
                ada.setCreatedAt(new Date(1700000001000L));
                ada.setPayload(new byte[] {10, 11, 12, 13});
                ada.setParent(grace);
            });
        } finally {
            realm.close();
        }
        return new File(configuration.getPath());
    }

    private static void verifySemanticRead(File directory, String name, byte[] key) {
        RealmConfiguration.Builder builder = new RealmConfiguration.Builder().directory(directory).name(name).schemaVersion(7);
        if (key != null) builder.encryptionKey(key);
        Realm realm = Realm.getInstance(builder.build());
        try {
            assertEquals(2, realm.where(FixturePerson.class).count());
            FixturePerson grace = realm.where(FixturePerson.class).equalTo("id", 100L).findFirst();
            FixturePerson ada = realm.where(FixturePerson.class).equalTo("id", 101L).findFirst();
            assertNotNull(grace);
            assertNotNull(ada);
            assertEquals("Grace", grace.getName());
            assertEquals(true, grace.isActive());
            assertEquals(1700000000000L, grace.getCreatedAt().getTime());
            assertArrayEquals(new byte[] {1, 2, 3, 4}, grace.getPayload());
            assertEquals("Ada", ada.getName());
            assertEquals(false, ada.isActive());
            assertEquals(1700000001000L, ada.getCreatedAt().getTime());
            assertArrayEquals(new byte[] {10, 11, 12, 13}, ada.getPayload());
            assertNotNull(ada.getParent());
            assertEquals(100L, ada.getParent().getId());
        } finally {
            realm.close();
        }
    }

    private static byte[] parseFixtureKey(String hex) {
        if (hex == null || !hex.matches("[0-9a-fA-F]{128}")) {
            throw new IllegalStateException("Provide FIXTURE_KEY_HEX as a 64-byte test-only environment secret");
        }
        byte[] key = new byte[64];
        for (int i = 0; i < key.length; i++) key[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
        return key;
    }

    private static void writeManifest(Context context, File output, File plain, File encrypted, byte[] key) throws Exception {
        String schema = readAsset(context, "schema.json");
        String golden = readAsset(context, "golden-data.json");
        String json = String.format(Locale.ROOT,
            "{\n  \"realm_version\": \"%s\",\n  \"official_artifact_manifest_sha256\": \"%s\",\n  \"schema_sha256\": \"%s\",\n  \"golden_data_sha256\": \"%s\",\n  \"encryption_key_sha256\": \"%s\",\n  \"plain_fixture_sha256\": \"%s\",\n  \"encrypted_fixture_sha256\": \"%s\",\n  \"official_reader_semantic_validation\": true,\n  \"sdk_int\": %d,\n  \"build_fingerprint\": \"%s\"\n}\n",
            REALM_VERSION, OFFICIAL_MANIFEST_SHA256, sha256(schema.getBytes(StandardCharsets.UTF_8)), sha256(golden.getBytes(StandardCharsets.UTF_8)),
            sha256(key), sha256File(plain), sha256File(encrypted), Build.VERSION.SDK_INT, Build.FINGERPRINT.replace("\\", "\\\\").replace("\"", "\\\""));
        try (FileOutputStream stream = new FileOutputStream(new File(output, "fixture-manifest.json"))) {
            stream.write(json.getBytes(StandardCharsets.UTF_8));
        }
    }

    private static String readAsset(Context context, String name) throws IOException {
        try (java.io.InputStream stream = context.getAssets().open(name)) {
            byte[] bytes = new byte[(int) stream.available()];
            int count = stream.read(bytes);
            if (count != bytes.length) throw new IOException("Incomplete asset read: " + name);
            return new String(bytes, StandardCharsets.UTF_8);
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

    private static String sha256(byte[] input) throws Exception {
        return hex(MessageDigest.getInstance("SHA-256").digest(input));
    }

    private static String hex(byte[] input) {
        StringBuilder result = new StringBuilder(input.length * 2);
        for (byte value : input) result.append(String.format(Locale.ROOT, "%02x", value & 0xff));
        return result.toString();
    }
}
