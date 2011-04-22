#!/bin/sh

# USAGE: ./tiro/system/bin/guard_file_name.sh <PERL_REGEX> <FAIL MESSAGE>

REGEX="$1"
MESSAGE="$2"

find "$TIRO_SUBMISSION_DIR" -type f -printf '%f\0' | \
    perl -0 -ne "chomp;
      if (!/$REGEX/) {
        print \"The filename '\$_' is invalid. \";
        print '$MESSAGE';
        exit 1;
      }"
