#!/bin/sh

set -eu
set -f

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
server_port=
next_is_server_port=0

for argument do
    if [ "$next_is_server_port" -eq 1 ]; then
        server_port=$argument
        next_is_server_port=0
    elif [ "$argument" = "-server" ]; then
        next_is_server_port=1
    fi
done

if [ -n "$server_port" ]; then
    exec docker run --rm -it \
        --cap-add=NET_ADMIN \
        --device=/dev/net/tun \
        -p "$server_port:$server_port/udp" \
        --mount type=bind,src="$script_dir",dst=/work,readonly \
        ipudp-development "$@"
else
    exec docker run --rm -it \
        --cap-add=NET_ADMIN \
        --device=/dev/net/tun \
        --mount type=bind,src="$script_dir",dst=/work,readonly \
        ipudp-development "$@"
fi
