#!/usr/bin/env bash
set -euo pipefail

vocabulary_name=96ca8ec8ea60b1f73465aaf2c401fd3b3ca75cdba2d3c50d6a2f6f760f275ddc-vocab_tree_faiss_flickr100K_words256K.bin
cache_directory="${HOME}/.cache/colmap"
cached_vocabulary="${cache_directory}/${vocabulary_name}"

if [ ! -f "$cached_vocabulary" ]; then
    mkdir -p "$cache_directory"
    temporary_vocabulary=$(mktemp "${cache_directory}/.vocabulary.XXXXXX")
    trap 'rm -f "$temporary_vocabulary"' EXIT
    cp "/opt/hud/colmap-cache/${vocabulary_name}" "$temporary_vocabulary"
    # Publish a complete file even when several jobs seed the cache together.
    chmod 644 "$temporary_vocabulary"
    mv -f "$temporary_vocabulary" "$cached_vocabulary"
    trap - EXIT
fi

exec /usr/local/libexec/colmap "$@"
