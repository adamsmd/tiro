#!/bin/sh
set -x
cp tiro.cgi demo/
cp system/lib/Tiro/Config.pm demo/system/lib/Tiro/
cp system/config.cfg demo/system/
cp config/* demo/config/
cp htaccess demo/.htaccess
cp htaccess_nonssl demo/.htaccess_nonssl
