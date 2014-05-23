#!/bin/sh

set -e
set -x

AUTH_TYPE="$1"
AUTH_NAME="$2"
HTTPS_URL="$3"

DST=dist

#umask 0000;

rm -f tiro/system/log/log-*.txt
rm -rf $DST

mkdir -m 755 $DST/
cat <<EOF >$DST/DIST_INFO
This directory was created by tiro/dist-prep.sh with the following options:

AUTH_TYPE=$AUTH_TYPE
AUTH_NAME=$AUTH_NAME
HTTPS_URL=$HTTPS_URL

Starting work ... (if the next line is not 'Finished!', then there was an err)
EOF
chmod 400 $DST/DIST_INFO
install -m 700 tiro/tiro.cgi $DST/
install -m 700 tiro/log.cgi $DST/

mkdir -m 700 -p $DST/assignments
install -m 644 tiro/assignments/.htaccess $DST/assignments/
install -m 600 tiro/assignments/a1.cfg.sample $DST/assignments/

mkdir -m 700 $DST/submissions
install -m 644 tiro/submissions/.htaccess $DST/submissions/

mkdir -m 700 $DST/system
install -m 644 tiro/system/.htaccess $DST/system
install -m 600 tiro/system/tiro.cfg.sample $DST/system/tiro.cfg.sample
install -m 600 tiro/system/users.csv.sample $DST/system/users.csv.sample
cp -r tiro/system/bin $DST/system
cp -r tiro/system/lib $DST/system
cp -r tiro/system/log $DST/system

cat <<EOF >$DST/.htaccess
SSLRequireSSL
#SSLOptions +StrictRequire
AuthType $AUTH_TYPE
AuthName "$AUTH_NAME"
Require valid-user

## Redirect non-https connections to https page
ErrorDocument 403 $HTTPS_URL
EOF
chmod 644 $DST/.htaccess

chmod 600 $DST/DIST_INFO
cat <<EOF >>$DST/DIST_INFO
... Finished!
EOF
chmod 400 $DST/DIST_INFO

set +x
echo
echo '  +++++++++++++++'
echo '  +++ SUCCESS +++'
echo '  +++++++++++++++'
echo
