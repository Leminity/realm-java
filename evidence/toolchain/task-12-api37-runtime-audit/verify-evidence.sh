#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
grep -qx '9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14' gradle-9.6.1-bin.zip.sha256
grep -q $'^build-tools;36.0.0\t36.0.0\tbuild-tools_r36_linux.zip\tlinux\t63737259\tb0b6376977657e8ad9b969bacf4093601da2c6fb$' repository-target-linux-archives.tsv
grep -q $'^ndk;29.0.14206865\t29.0.14206865\tandroid-ndk-r29-linux.zip\tlinux\t783549481\t87e2bb7e9be5d6a1c6cdf5ec40dd4e0c6d07c30b$' repository-target-linux-archives.tsv
grep -q '^system-images;android-37.1;google_apis_ps16k;x86_64$' sdkmanager-target-extract.txt
grep -q '^platforms;android-37.1$' sdkmanager-target-extract.txt
grep -qx 'sdkmanager exact cmake;3.27.7: ABSENT' cmake-3.27.7-absence-check.txt
grep -qx 'repository2-1.xml exact cmake;3.27.7: ABSENT' cmake-3.27.7-absence-check.txt
echo 'PASS: task-12 static evidence is internally consistent; runtime remains unexecuted.'
