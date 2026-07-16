# Official Maven download resolution

Initial request for `realm-android-kotlin-extensions-10.19.0.jar` returned HTTP 404.
The downloaded official POM declares `<packaging>aar</packaging>`, so the resolved
binary is `realm-android-kotlin-extensions-10.19.0.aar`. The original 404 was a
coordinate-extension discovery failure only; no artifact content was accepted from it.
