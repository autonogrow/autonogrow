#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_ROOT="${SOURCE_ROOT:-/opt/autonogrow}"
PUBLIC_ROOT="${PUBLIC_ROOT:-/var/www/autonogrow}"

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

install -d -o root -g root -m 0755 "$PUBLIC_ROOT"

for directory in "${PUBLIC_DIRECTORIES[@]}"; do
  source_directory="$SOURCE_ROOT/$directory"
  target_directory="$PUBLIC_ROOT/$directory"

  if [[ ! -d "$source_directory" ]]; then
    echo "ERROR: falta el directorio público: $source_directory" >&2
    exit 1
  fi

  echo "Publicando $directory"

  install -d -o root -g root -m 0755 "$target_directory"

  # Elimina archivos antiguos para que la copia pública refleje exactamente
  # el contenido de la versión desplegada.
  find "$target_directory" -mindepth 1 -delete

  cp -a "$source_directory/." "$target_directory/"
done

find "$PUBLIC_ROOT" -type d -exec chmod 0755 {} +
find "$PUBLIC_ROOT" -type f -exec chmod 0644 {} +
chown -R root:root "$PUBLIC_ROOT"

REQUIRED_FILES=(
  "$PUBLIC_ROOT/autonogrow-owner/index.html"
  "$PUBLIC_ROOT/autonogrow-admin/index.html"
  "$PUBLIC_ROOT/autonogrow-landing/index.html"
  "$PUBLIC_ROOT/autonogrow-customer/index.html"
  "$PUBLIC_ROOT/privacy/index.html"
  "$PUBLIC_ROOT/data-deletion/index.html"
)

for file in "${REQUIRED_FILES[@]}"; do
  if [[ ! -s "$file" ]]; then
    echo "ERROR: archivo público ausente o vacío: $file" >&2
    exit 1
  fi
done

echo "Frontend publicado correctamente en $PUBLIC_ROOT"
