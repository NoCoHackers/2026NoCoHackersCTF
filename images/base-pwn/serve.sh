#!/bin/sh
# Runs once per connection, as the `ctf` user, with the socket on stdio.
# Prints the event banner and then becomes the challenge.
[ -f /tmp/banner ] && cat /tmp/banner
exec "${CHAL_BIN:-/srv/chal}"
