#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_ROOT="${SOURCE_ROOT:-/opt/autonogrow}"
PUBLIC_ROOT="${PUBLIC_ROOT:-/var/www/autonogrow}"
RELEASES_ROOT="${RELEASES_ROOT:-/var/www/autonogrow-releases}"
RELEASE_ID="${RELEASE_ID:-$(git -C "$SOURCE_ROOT" rev-parse --short=12 HEAD)}"

PUBLIC_DIRECTORIES=(
  "autonogrow-owner"
  "autonogrow-admin"
  "autonogrow-landing"
  "autonogrow-customer"
  "autonogrow-shared"
  "privacy"
  "data-deletion"
)

if [[ ! -d "$SOURCE_ROOT" ]]; then
  echo "ERROR: no existe el repositorio: $SOURCE_ROOT" >&2
  exit 1
fi
if [[ ! "$RELEASE_ID" =~ ^[A-Za-z0-9._-]{7,120}$ ]]; then
  echo "ERROR: RELEASE_ID no es seguro" >&2
  exit 1
fi
if [[ -e "$PUBLIC_ROOT" && ! -L "$PUBLIC_ROOT" ]]; then
  echo "ERROR: $PUBLIC_ROOT debe ser un symlink para permitir publicación atómica." >&2
  echo "Conviértalo una sola vez siguiendo docs/staging_deploy_checklist.md." >&2
  exit 1
fi

install -d -o root -g root -m 0755 "$RELEASES_ROOT"
release_directory="$RELEASES_ROOT/$RELEASE_ID"
staging_directory="$RELEASES_ROOT/.${RELEASE_ID}.next"
next_link="${PUBLIC_ROOT}.next"

if [[ -e "$release_directory" || -e "$staging_directory" ]]; then
  echo "ERROR: ya existe la release frontend $RELEASE_ID" >&2
  exit 1
fi

cleanup() {
  rm -rf -- "$staging_directory"
  rm -f -- "$next_link"
}
trap cleanup EXIT
install -d -o root -g root -m 0755 "$staging_directory"

for directory in "${PUBLIC_DIRECTORIES[@]}"; do
  source_directory="$SOURCE_ROOT/$directory"
  if [[ ! -d "$source_directory" ]]; then
    echo "ERROR: falta el directorio público: $source_directory" >&2
    exit 1
  fi
  cp -a "$source_directory" "$staging_directory/$directory"
done

required_files=(
  "autonogrow-owner/index.html"
  "autonogrow-admin/index.html"
  "autonogrow-landing/index.html"
  "autonogrow-customer/index.html"
  "privacy/index.html"
  "data-deletion/index.html"
)
for file in "${required_files[@]}"; do
  if [[ ! -s "$staging_directory/$file" ]]; then
    echo "ERROR: archivo público ausente o vacío: $file" >&2
    exit 1
  fi
done

find "$staging_directory" -type d -exec chmod 0755 {} +
find "$staging_directory" -type f -exec chmod 0644 {} +
chown -R root:root "$staging_directory"
mv -- "$staging_directory" "$release_directory"
ln -s -- "$release_directory" "$next_link"
mv -Tf -- "$next_link" "$PUBLIC_ROOT"
trap - EXIT

echo "Frontend publicado atómicamente: $PUBLIC_ROOT -> $release_directory"
