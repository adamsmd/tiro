#!/bin/sh
set -x

DST=demo
AUTH_TYPE=KerberosV5
AUTH_NAME="UITS Network ID"
HTTPS_URL='https://www.cs.indiana.edu/~adamsmd/cgi-pub/tiro/tiro.cgi'

rm -f tiro/system/log/log-*.txt

cp tiro/tiro.cgi $DST/
cp -r tiro/system $DST
cp -r tiro/assignments $DST
cp -r tiro/submissions $DST

cat <<EOF >$DST/.htaccess
SSLRequireSSL
#SSLOptions +StrictRequire
AuthType $AUTH_TYPE
AuthName "$AUTH_NAME"
Require valid-user

## Redirect non-https connections to https page
ErrorDocument 403 $HTTPS_URL
EOF
