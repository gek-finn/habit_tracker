#!/bin/sh
# Installed at /etc/habit_tracker/certbot-deploy.sh, root:root 0700.
set -eu
if [ "${RENEWED_LINEAGE:-}" != "/etc/letsencrypt/live/habits.gilinsky.ru" ]; then
    exit 0
fi
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
echo "habit_tracker: Nginx проверен и плавно перезагружен после продления"
