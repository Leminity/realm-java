package io.realm.ac08.model;

import io.realm.RealmObject;
import io.realm.annotations.PrimaryKey;

/** A genuine static schema delta used only to record upstream no-migration exception parity. */
public class OfficialAddedAtNPlusOne extends RealmObject {
    @PrimaryKey private long id;

    public long getId() { return id; }
    public void setId(long id) { this.id = id; }
}
