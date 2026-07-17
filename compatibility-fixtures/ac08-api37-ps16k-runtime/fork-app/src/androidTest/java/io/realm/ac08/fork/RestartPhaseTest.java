package io.realm.ac08.fork;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.fail;

import android.content.Context;
import android.os.Process;
import android.os.SystemClock;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.runner.AndroidJUnit4;
import io.realm.DynamicRealm;
import io.realm.DynamicRealmObject;
import io.realm.FieldAttribute;
import io.realm.Realm;
import io.realm.RealmConfiguration;
import io.realm.RealmObjectSchema;
import io.realm.ac08.model.ForkNPlusOneModule;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Date;
import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * Host-run phase A/B test used to prove real process death preserves local plain and encrypted
 * data. Phase A must be externally force-stopped after it records the committed sentinels.
 */
@RunWith(AndroidJUnit4.class)
public final class RestartPhaseTest {
    private static final long SENTINEL_ID = 808L;
    private static final long SENTINEL_DATE = 1712345678000L;
    private static final byte[] SENTINEL_PAYLOAD = new byte[] { 8, 0, 8, 16 };

    @Test
    public void phaseACommitsSentinelsAndWaitsForForceStop() throws Exception {
        Context context = targetContext();
        Realm.init(context);
        RealmConfiguration plain = configuration(context, "restart-plain.realm", null);
        RealmConfiguration encrypted = configuration(context, "restart-encrypted.realm", key((byte) 23));
        Realm.deleteRealm(plain);
        Realm.deleteRealm(encrypted);
        seed(plain, "plain-phase-a");
        seed(encrypted, "encrypted-phase-a");
        verify(plain, "plain-phase-a");
        verify(encrypted, "encrypted-phase-a");
        writeEvidence(context, "restart-phase-a.txt", "A", Process.myPid());

        // The host waits for the evidence file, verifies this PID is live, then invokes
        // `am force-stop io.realm.ac08.fork`. Returning naturally is therefore a test failure.
        SystemClock.sleep(90000L);
        fail("Phase A must be terminated by the external force-stop before this timeout");
    }

    @Test
    public void phaseBReopensAndVerifiesSentinels() throws Exception {
        Context context = targetContext();
        Realm.init(context);
        RealmConfiguration plain = configuration(context, "restart-plain.realm", null);
        RealmConfiguration encrypted = configuration(context, "restart-encrypted.realm", key((byte) 23));
        verify(plain, "plain-phase-a");
        verify(encrypted, "encrypted-phase-a");
        writeEvidence(context, "restart-phase-b.txt", "B", Process.myPid());
    }

    private static RealmConfiguration configuration(Context context, String name, byte[] encryptionKey) {
        RealmConfiguration.Builder builder = new RealmConfiguration.Builder()
                .directory(testDirectory(context))
                .name(name)
                .modules(new ForkNPlusOneModule())
                .schemaVersion(1L);
        if (encryptionKey != null) builder.encryptionKey(encryptionKey);
        return builder.build();
    }

    private static void seed(RealmConfiguration configuration, String expectedName) {
        DynamicRealm realm = DynamicRealm.getInstance(configuration);
        try {
            realm.beginTransaction();
            RealmObjectSchema sentinel = realm.getSchema().create("RestartSentinel")
                    .addField("id", long.class, FieldAttribute.PRIMARY_KEY)
                    .addField("name", String.class)
                    .addField("createdAt", Date.class)
                    .addField("payload", byte[].class);
            DynamicRealmObject object = realm.createObject("RestartSentinel", SENTINEL_ID);
            object.setString("name", expectedName);
            object.setDate("createdAt", new Date(SENTINEL_DATE));
            object.setBlob("payload", SENTINEL_PAYLOAD);
            assertNotNull(sentinel);
            realm.commitTransaction();
        } finally {
            if (realm.isInTransaction()) realm.cancelTransaction();
            realm.close();
        }
    }

    private static void verify(RealmConfiguration configuration, String expectedName) {
        DynamicRealm realm = DynamicRealm.getInstance(configuration);
        try {
            DynamicRealmObject object = realm.where("RestartSentinel").equalTo("id", SENTINEL_ID).findFirst();
            assertNotNull("Restart sentinel must survive process recreation", object);
            assertEquals(expectedName, object.getString("name"));
            assertEquals(new Date(SENTINEL_DATE), object.getDate("createdAt"));
            assertArrayEquals(SENTINEL_PAYLOAD, object.getBlob("payload"));
        } finally {
            realm.close();
        }
    }

    private static void writeEvidence(Context context, String name, String phase, int pid) throws Exception {
        File output = new File(testDirectory(context), name);
        String body = "phase=" + phase + "\n"
                + "pid=" + pid + "\n"
                + "plain=plain-phase-a|" + SENTINEL_DATE + "|" + Arrays.toString(SENTINEL_PAYLOAD) + "\n"
                + "encrypted=encrypted-phase-a|" + SENTINEL_DATE + "|" + Arrays.toString(SENTINEL_PAYLOAD) + "\n";
        try (FileOutputStream stream = new FileOutputStream(output)) {
            stream.write(body.getBytes(StandardCharsets.UTF_8));
        }
    }

    private static Context targetContext() {
        return InstrumentationRegistry.getInstrumentation().getTargetContext();
    }

    private static File testDirectory(Context context) {
        File directory = new File(context.getFilesDir(), "ac08");
        if (!directory.exists() && !directory.mkdirs()) throw new IllegalStateException("Cannot create " + directory);
        return directory;
    }

    private static byte[] key(byte first) {
        byte[] result = new byte[64];
        Arrays.fill(result, first);
        return result;
    }
}
