# AC-09 digest evidence

logical-digest-inventory.txt is the canonical AC-09 verifier logical digest
inventory. Its official/ and fork/ names identify compared artifact roles;
they are not materialized relative filesystem paths and the inventory must not
be passed to sha256sum -c.

SHA256SUMS is the replayable filesystem seal for the materialized evidence in
this directory. checksum-verify.log records a successful replay.
