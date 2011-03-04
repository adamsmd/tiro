#!/bin/sh
set -x
cp tiro.cgi tiro/
cp config/* tiro/config/
cp htaccess tiro/.htaccess
cp htaccess_nonssl tiro/.htaccess_nonssl
