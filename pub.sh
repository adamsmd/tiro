#!/bin/sh
set -x
cp tiro.cgi demo/
cp system/config.cfg system/users.csv demo/system/
cp system/bin/* demo/system/bin/
cp system/lib/Tiro/Config.pm demo/system/lib/Tiro/
rm system/log/log.txt
cp htaccess demo/.htaccess
cp htaccess_nonssl demo/.htaccess_nonssl
