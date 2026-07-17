package io.realm.fixtureac07fork;

import android.app.Application;
import io.realm.Realm;

public final class ForkConsumerApplication extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        Realm.init(this);
    }
}
