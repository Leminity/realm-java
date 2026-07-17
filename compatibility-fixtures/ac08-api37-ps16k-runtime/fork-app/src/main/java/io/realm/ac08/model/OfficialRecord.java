package io.realm.ac08.model;

import io.realm.RealmObject;
import io.realm.annotations.PrimaryKey;
import java.util.Date;

/** Schema N+1 as interpreted by the local G008 fork build. */
public class OfficialRecord extends RealmObject {
    @PrimaryKey private long id;
    private String name;
    private Date createdAt;
    private byte[] payload;
    private String forkMigrationNote;

    public long getId() { return id; }
    public void setId(long id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date createdAt) { this.createdAt = createdAt; }
    public byte[] getPayload() { return payload; }
    public void setPayload(byte[] payload) { this.payload = payload; }
    public String getForkMigrationNote() { return forkMigrationNote; }
    public void setForkMigrationNote(String forkMigrationNote) { this.forkMigrationNote = forkMigrationNote; }
}
