#!/bin/bash

set -x
IPUDP_KEY=abcdef0123456789
IPUDP_PORT=48625

docker run --rm -it \
    --cap-add=NET_ADMIN \
    --device=/dev/net/tun \
    -p $IPUDP_PORT:$IPUDP_PORT/udp \
    -e IPUDP_KEY=$IPUDP_KEY \
    -e IPUDP_PORT=$IPUDP_PORT \
    --mount type=bind,src="$PWD",dst=/work,readonly \
    ipudp-server
