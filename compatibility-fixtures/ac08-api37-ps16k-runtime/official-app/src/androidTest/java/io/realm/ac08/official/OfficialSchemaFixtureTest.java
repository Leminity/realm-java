package io.realm.ac08.official;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.fail;

import android.content.Context;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.runner.AndroidJUnit4;
import io.realm.Realm;
import io.realm.RealmConfiguration;
import io.realm.RealmResults;
import io.realm.ac08.model.OfficialRecord;
import io.realm.ac08.model.SchemaNModule;
import io.realm.ac08.model.SchemaNPlusOneModule;
import io.realm.exceptions.RealmMigrationNeededException;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * Creates a real static-schema Realm using only upstream io.realm:10.19.0.  This runs in a
 * separate Gradle build from the fork, so its generated proxy/schema cannot be supplied by the
 * local G008 plugin.
 */
@RunWith(AndroidJUnit4.class)
public final class OfficialSchemaFixtureTest {
    private static final long SCHEMA_N = 700L;

    @Test
    public void createOfficialSchemaNAndRecordBaselineExceptionCategories() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        Realm.init(context);
        File directory = new File(context.getFilesDir(), "ac08");
        if (!directory.exists() && !directory.mkdirs()) throw new IllegalStateException("Cannot create " + directory);

        RealmConfiguration schemaN = new RealmConfiguration.Builder()
                .directory(directory)
                .name("official-schema-n.realm")
                .modules(new SchemaNModule())
                .schemaVersion(SCHEMA_N)
                .build();
        Realm.deleteRealm(schemaN);
        Realm realm = Realm.getInstance(schemaN);
        try {
            realm.executeTransaction(new Realm.Transaction() {
                @Override public void execute(Realm transaction) {
                    OfficialRecord record = transaction.createObject(OfficialRecord.class, 1L);
                    record.setName("official-schema-n");
                    record.setCreatedAt(new Date(1700000000000L));
                    record.setPayload(new byte[] { 7, 0, 0 });
                }
            });
            assertNotNull(realm.where(OfficialRecord.class).equalTo("id", 1L).findFirst());
        } finally {
            realm.close();
        }

        write(new File(directory, "no-migration-category.txt"), noMigrationCategory(directory));
        write(new File(directory, "thread-categories.txt"), threadCategories(schemaN));
    }

    private static String noMigrationCategory(File directory) {
        try {
            Realm noMigration = Realm.getInstance(new RealmConfiguration.Builder()
                    .directory(directory)
                    .name("official-schema-n.realm")
                    .modules(new SchemaNPlusOneModule())
                    .schemaVersion(SCHEMA_N + 1L)
                    .build());
            noMigration.close();
            fail("Expected schema N opened as N+1 without a migration to fail");
            return "unreachable";
        } catch (RealmMigrationNeededException expected) {
            return expected.getClass().getName();
        }
    }

    private static String threadCategories(RealmConfiguration configuration) throws Exception {
        final Realm ownerThreadRealm = Realm.getInstance(configuration);
        try {
            final OfficialRecord managed = ownerThreadRealm.where(OfficialRecord.class).equalTo("id", 1L).findFirst();
            final RealmResults<OfficialRecord> results = ownerThreadRealm.where(OfficialRecord.class).findAll();
            assertNotNull(managed);
            return "realm=" + foreignThreadFailure("realm", new Runnable() {
                        @Override public void run() { ownerThreadRealm.where(OfficialRecord.class).count(); }
                    }).getClass().getName() + "\n"
                    + "managed_object=" + foreignThreadFailure("managed object", new Runnable() {
                        @Override public void run() { managed.getName(); }
                    }).getClass().getName() + "\n"
                    + "results=" + foreignThreadFailure("results", new Runnable() {
                        @Override public void run() { results.size(); }
                    }).getClass().getName() + "\n";
        } finally {
            ownerThreadRealm.close();
        }
    }

    private static Throwable foreignThreadFailure(final String label, final Runnable access) throws Exception {
        final AtomicReference<Throwable> thrown = new AtomicReference<>();
        Thread foreignThread = new Thread(new Runnable() {
            @Override public void run() {
                try {
                    access.run();
                } catch (Throwable error) {
                    thrown.set(error);
                }
            }
        }, "official-ac08-foreign-" + label.replace(' ', '-'));
        foreignThread.start();
        foreignThread.join(10000L);
        assertNotNull("Official baseline must reject " + label + " access from a foreign thread", thrown.get());
        return thrown.get();
    }

    private static void write(File output, String value) throws Exception {
        try (FileOutputStream stream = new FileOutputStream(output)) {
            stream.write(value.getBytes(StandardCharsets.UTF_8));
        }
    }
}
