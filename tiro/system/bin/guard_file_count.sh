#!/bin/sh

# USAGE: ./system/bin/guard_file_count.sh <MIN COUNT> <MAX COUNT>

LOW="$1"
HIGH="$2"

COUNT=$(find "$TIRO_SUBMISSION_DIR" -type f -printf "\n" | wc -l)

if [ $COUNT -lt $LOW ]; then
    echo "Too few files.  Expecting at least $LOW file(s) but found $COUNT."
    exit 1
elif [ $COUNT -gt $HIGH ]; then
    echo "Too many files.  Expecting at most $HIGH file(s) but found $COUNT."
    exit 1
fi
