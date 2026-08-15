#!/bin/bash

set -x

if test "$#" -ne 1; then
    echo "Illegal number of parameters"
    exit 1
fi

IPUDP_KEY=abcdef0123456789
IPUDP_PORT=48625

exec docker run --rm -it \
    --cap-add=NET_ADMIN \
    --device=/dev/net/tun \
    -e IPUDP_KEY=$IPUDP_KEY \
    -e IPUDP_PORT=$IPUDP_PORT \
    -e IPUDP_SERVER_IP=$1 \
    --mount type=bind,src="$PWD",dst=/work,readonly \
    ipudp-client
