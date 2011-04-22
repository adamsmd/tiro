#!/bin/sh

# USAGE: ./system/bin/guard_file_count.sh <MIN BYTES> <MAX BYTES>

LOW="$1"
HIGH="$2"

TOO_SMALL=$(find "$TIRO_SUBMISSION_DIR" -type f -size -"$LOW"c)
TOO_LARGE=$(find "$TIRO_SUBMISSION_DIR" -type f -size +"$HIGH"c)

if [ -n "$TOO_SMALL" ]; then
    echo "Files too small ($TOO_SMALL)."
    echo "Expecting files of at least $LOW bytes."
    exit 1;
fi

if [ -n "$TOO_LARGE" ]; then
    echo "Files too large ($TOO_LARGE)."
    echo "Expecting files of at most $HIGH bytes."
    exit 1;
fi
