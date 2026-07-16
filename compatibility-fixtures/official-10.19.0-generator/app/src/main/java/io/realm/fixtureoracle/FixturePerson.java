package io.realm.fixtureoracle;

import java.util.Date;
import io.realm.RealmObject;
import io.realm.annotations.PrimaryKey;

public class FixturePerson extends RealmObject {
    @PrimaryKey
    private long id;
    private String name;
    private boolean active;
    private Date createdAt;
    private byte[] payload;
    private FixturePerson parent;

    public long getId() { return id; }
    public void setId(long id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public boolean isActive() { return active; }
    public void setActive(boolean active) { this.active = active; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date createdAt) { this.createdAt = createdAt; }
    public byte[] getPayload() { return payload; }
    public void setPayload(byte[] payload) { this.payload = payload; }
    public FixturePerson getParent() { return parent; }
    public void setParent(FixturePerson parent) { this.parent = parent; }
}
