package io.realm.fixtureoracle;

import android.app.Application;
import io.realm.Realm;

public final class FixtureOracleApplication extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        Realm.init(this);
    }
}
