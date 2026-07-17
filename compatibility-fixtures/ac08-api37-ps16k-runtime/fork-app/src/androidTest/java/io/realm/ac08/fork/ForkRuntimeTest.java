package io.realm.ac08.fork;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import android.app.Instrumentation;
import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.runner.AndroidJUnit4;
import io.realm.DynamicRealm;
import io.realm.DynamicRealmObject;
import io.realm.FieldAttribute;
import io.realm.Realm;
import io.realm.RealmChangeListener;
import io.realm.RealmConfiguration;
import io.realm.RealmList;
import io.realm.RealmMigration;
import io.realm.RealmObjectSchema;
import io.realm.RealmResults;
import io.realm.RealmSchema;
import io.realm.ac08.model.ForkNPlusOneModule;
import io.realm.ac08.model.OfficialRecord;
import io.realm.exceptions.RealmMigrationNeededException;
import io.realm.exceptions.RealmPrimaryKeyConstraintException;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Date;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.Test;
import org.junit.runner.RunWith;

/** AC-08 runtime checks executed directly against the local G008 fork artifacts. */
@RunWith(AndroidJUnit4.class)
public final class ForkRuntimeTest {
    private static final long SCHEMA_N = 700L;
    private static final long SCHEMA_N_PLUS_ONE = 701L;

    @Test
    public void plainEncryptedInitOpenCloseCommitRollbackCrudQueryLinkListNullDateBinaryAndPrimaryKey() throws Exception {
        Context context = targetContext();
        Realm.init(context);
        File directory = testDirectory(context);
        RealmConfiguration plain = configuration(directory, "fork-plain.realm", null, 1L, null);
        RealmConfiguration encrypted = configuration(directory, "fork-encrypted.realm", key((byte) 9), 1L, null);

        Realm.deleteRealm(plain);
        Realm.deleteRealm(encrypted);
        seedAndAssert(plain);
        seedAndAssert(encrypted);

        DynamicRealm reopenedPlain = DynamicRealm.getInstance(plain);
        DynamicRealm reopenedEncrypted = DynamicRealm.getInstance(encrypted);
        try {
            assertEquals(1L, reopenedPlain.where("Parent").count());
            assertEquals(1L, reopenedEncrypted.where("Parent").count());
        } finally {
            reopenedPlain.close();
            reopenedEncrypted.close();
        }
    }

    @Test
    public void notificationThenUnsubscribeStopsFurtherDelivery() throws Exception {
        final RealmConfiguration configuration = freshPlainConfiguration("notifications.realm");
        seedAndAssert(configuration);
        final Instrumentation instrumentation = InstrumentationRegistry.getInstrumentation();
        final AtomicInteger deliveries = new AtomicInteger();
        final CountDownLatch committedDelivery = new CountDownLatch(1);
        final AtomicReference<DynamicRealm> reference = new AtomicReference<>();
        final RealmChangeListener<DynamicRealm> listener = new RealmChangeListener<DynamicRealm>() {
            @Override public void onChange(DynamicRealm realm) {
                deliveries.incrementAndGet();
                committedDelivery.countDown();
            }
        };

        instrumentation.runOnMainSync(new Runnable() {
            @Override public void run() {
                DynamicRealm realm = DynamicRealm.getInstance(configuration);
                reference.set(realm);
                realm.addChangeListener(listener);
                realm.executeTransaction(new DynamicRealm.Transaction() {
                    @Override public void execute(DynamicRealm transaction) {
                        transaction.where("Parent").equalTo("id", 1L).findFirst().setString("name", "notified");
                    }
                });
            }
        });
        assertTrue("A committed transaction must notify an active listener", committedDelivery.await(10, TimeUnit.SECONDS));
        final int beforeUnsubscribe = deliveries.get();

        instrumentation.runOnMainSync(new Runnable() {
            @Override public void run() {
                DynamicRealm realm = reference.get();
                realm.removeChangeListener(listener);
                realm.executeTransaction(new DynamicRealm.Transaction() {
                    @Override public void execute(DynamicRealm transaction) {
                        transaction.where("Parent").equalTo("id", 1L).findFirst().setString("name", "unsubscribed");
                    }
                });
                realm.close();
            }
        });
        Thread.sleep(500L);
        assertEquals("Unsubscribed listeners must receive no later delivery", beforeUnsubscribe, deliveries.get());
    }

    @Test
    public void invalidThreadMatchesOfficialBaselineCategory() throws Exception {
        final RealmConfiguration configuration = freshPlainConfiguration("invalid-thread.realm");
        seedAndAssert(configuration);
        final DynamicRealm ownerThreadRealm = DynamicRealm.getInstance(configuration);
        final AtomicReference<Throwable> thrown = new AtomicReference<>();
        Thread foreignThread = new Thread(new Runnable() {
            @Override public void run() {
                try {
                    ownerThreadRealm.where("Parent").count();
                } catch (Throwable error) {
                    thrown.set(error);
                }
            }
        }, "fork-ac08-foreign-realm-thread");
        foreignThread.start();
        foreignThread.join(10000L);
        ownerThreadRealm.close();
        assertNotNull("Realm access from a non-owner thread must fail", thrown.get());
        assertEquals("Fork invalid-thread category must match the isolated official baseline",
                requiredArgument("official_invalid_thread_category"), thrown.get().getClass().getName());
    }

    @Test
    public void wrongKeyRejectsAndDoesNotMutateImmutableEncryptedSource() throws Exception {
        Context context = targetContext();
        File source = requiredInput(context, "official-encrypted.realm");
        String expectedHash = requiredArgument("encrypted_sha256");
        assertEquals(expectedHash, sha256(source));
        File work = new File(testDirectory(context), "wrong-key-work.realm");
        copy(source, work);
        RealmConfiguration wrongKey = new RealmConfiguration.Builder()
                .directory(work.getParentFile())
                .name(work.getName())
                .encryptionKey(key((byte) 1))
                .build();
        boolean rejected = false;
        try {
            DynamicRealm realm = DynamicRealm.getInstance(wrongKey);
            realm.close();
        } catch (RuntimeException expected) {
            rejected = true;
        }
        assertTrue("A wrong encryption key must be rejected", rejected);
        assertEquals("The immutable encrypted source must remain byte-identical", expectedHash, sha256(source));
    }

    @Test
    public void officialSchemaNToForkNPlusOneMigratesOnceReopensWithoutMigrationAndMatchesBaselineCategory() throws Exception {
        Context context = targetContext();
        File source = requiredInput(context, "official-schema-n.realm");
        assertEquals(requiredArgument("schema_sha256"), sha256(source));
        File working = new File(testDirectory(context), "official-schema-n-fork-working.realm");
        copy(source, working);

        final AtomicInteger callbacks = new AtomicInteger();
        RealmConfiguration migratedConfig = new RealmConfiguration.Builder()
                .directory(working.getParentFile())
                .name(working.getName())
                .modules(new ForkNPlusOneModule())
                .schemaVersion(SCHEMA_N_PLUS_ONE)
                .migration(new RealmMigration() {
                    @Override public void migrate(DynamicRealm realm, long oldVersion, long newVersion) {
                        assertEquals(SCHEMA_N, oldVersion);
                        assertEquals(SCHEMA_N_PLUS_ONE, newVersion);
                        callbacks.incrementAndGet();
                        RealmObjectSchema record = realm.getSchema().get("OfficialRecord");
                        assertNotNull(record);
                        record.addField("forkMigrationNote", String.class);
                        DynamicRealmObject object = realm.where("OfficialRecord").equalTo("id", 1L).findFirst();
                        assertNotNull(object);
                        object.setString("forkMigrationNote", "fork-n-plus-one");
                    }
                })
                .build();
        Realm migrated = Realm.getInstance(migratedConfig);
        try {
            OfficialRecord record = migrated.where(OfficialRecord.class).equalTo("id", 1L).findFirst();
            assertNotNull(record);
            assertEquals("official-schema-n", record.getName());
            assertEquals("fork-n-plus-one", record.getForkMigrationNote());
        } finally {
            migrated.close();
        }
        assertEquals("Migration runs exactly once on N -> N+1", 1, callbacks.get());

        Realm reopened = Realm.getInstance(migratedConfig);
        try {
            assertEquals("fork-n-plus-one", reopened.where(OfficialRecord.class).equalTo("id", 1L)
                    .findFirst().getForkMigrationNote());
        } finally {
            reopened.close();
        }
        assertEquals("Reopen at N+1 must not migrate again", 1, callbacks.get());

        File noMigration = new File(testDirectory(context), "official-schema-n-no-migration.realm");
        copy(source, noMigration);
        try {
            Realm realm = Realm.getInstance(new RealmConfiguration.Builder()
                    .directory(noMigration.getParentFile())
                    .name(noMigration.getName())
                    .modules(new ForkNPlusOneModule())
                    .schemaVersion(SCHEMA_N_PLUS_ONE)
                    .build());
            realm.close();
            fail("Schema N opened at N+1 without a migration must fail");
        } catch (RealmMigrationNeededException expected) {
            assertEquals("Fork no-migration category must match the official baseline",
                    requiredArgument("official_no_migration_category"), expected.getClass().getName());
        }
        assertEquals("Migration input is never modified", requiredArgument("schema_sha256"), sha256(source));
    }

    @Test
    public void packageHasNoSyncAccountServiceOrNetworkConfiguration() throws Exception {
        Context context = targetContext();
        PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(),
                PackageManager.GET_PERMISSIONS | PackageManager.GET_SERVICES | PackageManager.GET_PROVIDERS);
        String[] permissions = info.requestedPermissions == null ? new String[0] : info.requestedPermissions;
        assertFalse(Arrays.asList(permissions).contains("android.permission.INTERNET"));
        assertFalse(Arrays.asList(permissions).contains("android.permission.ACCESS_NETWORK_STATE"));
        assertFalse(Arrays.asList(permissions).contains("android.permission.GET_ACCOUNTS"));
        assertEquals("The harness declares no services (including sync/account services)", 0,
                info.services == null ? 0 : info.services.length);
        assertEquals("The harness declares no providers", 0, info.providers == null ? 0 : info.providers.length);
        assertNotNull("Realm.init creates only the ordinary local default configuration", Realm.getDefaultConfiguration());
        assertEquals("The default configuration must be the local Realm type, never a Sync configuration",
                RealmConfiguration.class.getName(), Realm.getDefaultConfiguration().getClass().getName());
    }

    private static void seedAndAssert(RealmConfiguration configuration) {
        DynamicRealm realm = DynamicRealm.getInstance(configuration);
        try {
            realm.beginTransaction();
            RealmSchema schema = realm.getSchema();
            RealmObjectSchema child = schema.create("Child")
                    .addField("id", long.class, FieldAttribute.PRIMARY_KEY)
                    .addField("name", String.class);
            RealmObjectSchema parent = schema.create("Parent")
                    .addField("id", long.class, FieldAttribute.PRIMARY_KEY)
                    .addField("name", String.class)
                    .addField("note", String.class)
                    .addField("when", Date.class)
                    .addField("payload", byte[].class)
                    .addRealmObjectField("child", child)
                    .addRealmListField("children", child);
            DynamicRealmObject aChild = realm.createObject("Child", 7L);
            aChild.setString("name", "linked-child");
            DynamicRealmObject parentObject = realm.createObject("Parent", 1L);
            parentObject.setString("name", "committed");
            parentObject.setNull("note");
            parentObject.setDate("when", new Date(1700000000000L));
            parentObject.setBlob("payload", new byte[] { 1, 2, 3 });
            parentObject.setObject("child", aChild);
            parentObject.setList("children", new RealmList<DynamicRealmObject>(aChild));
            realm.commitTransaction();

            realm.beginTransaction();
            realm.createObject("Parent", 2L).setString("name", "rolled-back");
            realm.cancelTransaction();

            RealmResults<DynamicRealmObject> results = realm.where("Parent").equalTo("id", 1L).findAll();
            assertEquals(1, results.size());
            DynamicRealmObject committed = results.first();
            assertEquals("committed", committed.getString("name"));
            assertTrue(realm.where("Parent").isNull("note").findAll().size() == 1);
            assertEquals(new Date(1700000000000L), committed.getDate("when"));
            assertArrayEquals(new byte[] { 1, 2, 3 }, committed.getBlob("payload"));
            assertEquals(7L, committed.getObject("child").getLong("id"));
            assertEquals(1, committed.<DynamicRealmObject>getList("children").size());
            assertEquals(7L, committed.<DynamicRealmObject>getList("children").first().getLong("id"));
            assertEquals(0L, realm.where("Parent").equalTo("id", 2L).count());

            realm.executeTransaction(new DynamicRealm.Transaction() {
                @Override public void execute(DynamicRealm transaction) {
                    transaction.where("Parent").equalTo("id", 1L).findFirst().setString("name", "updated");
                    transaction.createObject("Parent", 3L).setString("name", "deleted");
                }
            });
            assertEquals("updated", realm.where("Parent").equalTo("id", 1L).findFirst().getString("name"));
            realm.executeTransaction(new DynamicRealm.Transaction() {
                @Override public void execute(DynamicRealm transaction) {
                    transaction.where("Parent").equalTo("id", 3L).findFirst().deleteFromRealm();
                }
            });
            assertEquals(0L, realm.where("Parent").equalTo("id", 3L).count());

            realm.beginTransaction();
            try {
                realm.createObject("Parent", 1L);
                fail("Duplicate primary keys must be rejected");
            } catch (RealmPrimaryKeyConstraintException expected) {
                // Expected: a dynamic schema primary key enforces uniqueness.
            } finally {
                if (realm.isInTransaction()) realm.cancelTransaction();
            }
        } finally {
            if (realm.isInTransaction()) realm.cancelTransaction();
            realm.close();
        }
    }

    private static RealmConfiguration freshPlainConfiguration(String name) {
        Context context = targetContext();
        Realm.init(context);
        RealmConfiguration configuration = configuration(testDirectory(context), name, null, 1L, null);
        Realm.deleteRealm(configuration);
        return configuration;
    }

    private static RealmConfiguration configuration(File directory, String name, byte[] encryptionKey,
            long version, RealmMigration migration) {
        RealmConfiguration.Builder builder = new RealmConfiguration.Builder()
                .directory(directory)
                .name(name)
                .modules(new ForkNPlusOneModule())
                .allowWritesOnUiThread(true)
                .schemaVersion(version);
        if (encryptionKey != null) builder.encryptionKey(encryptionKey);
        if (migration != null) builder.migration(migration);
        return builder.build();
    }

    private static Context targetContext() {
        return InstrumentationRegistry.getInstrumentation().getTargetContext();
    }

    private static File testDirectory(Context context) {
        File directory = new File(context.getFilesDir(), "ac08");
        if (!directory.exists() && !directory.mkdirs()) throw new IllegalStateException("Cannot create " + directory);
        return directory;
    }

    private static File requiredInput(Context context, String name) {
        File input = new File(testDirectory(context), name);
        assertTrue("Host runner did not install required immutable input " + name, input.isFile());
        return input;
    }

    private static String requiredArgument(String name) {
        String value = InstrumentationRegistry.getArguments().getString(name);
        assertNotNull("Host runner omitted instrumentation argument " + name, value);
        return value;
    }

    private static byte[] key(byte first) {
        byte[] result = new byte[64];
        Arrays.fill(result, first);
        return result;
    }

    private static void copy(File source, File destination) throws IOException {
        try (FileInputStream input = new FileInputStream(source); FileOutputStream output = new FileOutputStream(destination)) {
            byte[] buffer = new byte[8192];
            for (int read; (read = input.read(buffer)) != -1;) output.write(buffer, 0, read);
        }
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (FileInputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[8192];
            for (int read; (read = input.read(buffer)) != -1;) digest.update(buffer, 0, read);
        }
        StringBuilder result = new StringBuilder(64);
        for (byte value : digest.digest()) result.append(String.format("%02x", value & 0xff));
        return result.toString();
    }
}
