#!/bin/sh
set -eu
printf '%s\n' "$FIXTURE_NODE_ID" > /etc/machine-id
install -d -m 700 -o fixture -g fixture /home/fixture/.ssh
install -m 600 -o fixture -g fixture /fixture/client_key.pub /home/fixture/.ssh/authorized_keys
runuser -u fixture -- tmux -L pimux -f /dev/null new-session -d -s shared 'sleep 14400'
runuser -u fixture -- tmux -L untouched -f /dev/null new-session -d -s sentinel 'sleep 14400'
exec /usr/sbin/sshd -D -e
