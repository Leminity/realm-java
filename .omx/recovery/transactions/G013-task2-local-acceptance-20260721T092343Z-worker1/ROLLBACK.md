# Rollback

This transaction records local evidence plus the approved generated G011 source
manifest refresh already committed at 188f0832252172a5ca93204292a65a0f8fe4f4f3.

To restore the pre-refresh manifest at the current source commit, first run:
  git apply --check rollback/manifest-rollback.patch
Then apply:
  git apply rollback/manifest-rollback.patch
The restored manifest must match rollback/g011-source-evidence-manifest.pre.json
with SHA-256 10f6ec7799891df0e39f1bad0232a63e2f655f1bfefade5877ee8e03b862aea0.

The patch check was replayed successfully during final sealing. To remove only
the evidence transaction after integration, revert the evidence commit recorded
as this transaction commit. Generated build outputs and local caches are ignored
and may be deleted independently.
