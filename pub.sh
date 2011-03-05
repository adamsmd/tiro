#!/bin/sh
set -x
cp tiro.cgi demo/
cp config/* demo/config/
cp htaccess demo/.htaccess
cp htaccess_nonssl demo/.htaccess_nonssl
