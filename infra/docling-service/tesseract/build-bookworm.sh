#!/bin/sh
set -eu

patch_path="$1"
output="$2"
source_pool=https://deb.debian.org/debian/pool/main/t/tesseract
base_version=5.3.0-2
version=5.3.0-2+kamilya2
export DEBIAN_FRONTEND=noninteractive
export DEB_BUILD_OPTIONS="nocheck parallel=2"

apt-get -o Acquire::Retries=1 update
apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl debhelper libleptonica-dev automake libtool \
    libarchive-dev libpango1.0-dev libcairo2-dev libicu-dev libpng-dev libjpeg-dev \
    libtiff-dev zlib1g-dev git asciidoc xsltproc docbook-xsl docbook-xml \
    tesseract-ocr-eng dh-autoreconf autoconf-archive libcurl4-openssl-dev

work="$(mktemp -d)"
cd "$work"
for archive in tesseract_5.3.0.orig.tar.gz "tesseract_${base_version}.debian.tar.xz"; do
    curl --fail --silent --show-error --location --max-time 60 "$source_pool/$archive" --output "$archive"
done
sha256sum -c <<'CHECKSUMS'
7e70870f8341e5ea228af2836ce79a36eefa11b01b56177b4a8997f330c014b8  tesseract_5.3.0.orig.tar.gz
25f7cc88884a1873a2f8f6ea9175655f99b0613e8b6cf612d9a9cf6ebd120fe5  tesseract_5.3.0-2.debian.tar.xz
CHECKSUMS
mkdir source
tar -xzf tesseract_5.3.0.orig.tar.gz --strip-components=1 -C source
tar -xJf "tesseract_${base_version}.debian.tar.xz" -C source
cd source
install -m 0644 "$patch_path" debian/patches/kamilya-bookworm-security.patch
printf '\n%s\n' kamilya-bookworm-security.patch >> debian/patches/series
cat > changelog.kamilya <<'CHANGELOG'
tesseract (5.3.0-2+kamilya2) bookworm; urgency=high

  * Backport upstream raster OCR bounds and overflow fixes from 5.5.5.

 -- Kamilya LMS <engineering@kml.kz>  Fri, 27 Nov 2026 10:00:00 +0500

CHANGELOG
cat changelog.kamilya debian/changelog > debian/changelog.new
mv debian/changelog.new debian/changelog

# Reuse the matching Debian man pages. The backport does not change the CLI.
(
    cd "$work"
    apt-get download "tesseract-ocr=$base_version"
    dpkg-deb -x "tesseract-ocr_${base_version}_$(dpkg --print-architecture).deb" stock
)
cp -a "$work/stock/usr/share/man" debian/stock-man
sed -i 's/--disable-tessdata-prefix/--disable-doc --disable-tessdata-prefix/' debian/rules
sed -i '/training-install/a\	mkdir -p debian/tmp/usr/share/man\n\tcp -a debian/stock-man/. debian/tmp/usr/share/man/' debian/rules
dpkg-buildpackage -us -uc -b -j2
arch="$(dpkg --print-architecture)"
for name in libtesseract5 tesseract-ocr; do
    package="../${name}_${version}_${arch}.deb"
    test "$(dpkg-deb -f "$package" Version)" = "$version"
    install -m 0644 "$package" "$output/$name.deb"
done
