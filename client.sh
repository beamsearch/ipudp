#!/bin/sh

set -eu
set -f

CLIENT_TUN_IP=10.0.1.1
SERVER_TUN_IP=10.0.1.2
STATE_ROOT=${IPUDP_STATE_DIR:-/run/ipudp}

: "${TUN_NAME:?TUN_NAME is required}"
: "${REMOTE_IP:?REMOTE_IP is required}"

if ! command -v ip >/dev/null 2>&1; then
    echo "iproute2 is required" >&2
    exit 1
fi

case "$TUN_NAME" in
    *[!A-Za-z0-9_.-]*)
        echo "unsupported TUN device name: $TUN_NAME" >&2
        exit 1
        ;;
esac

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
state_dir="$STATE_ROOT/client-$TUN_NAME"

umask 077
mkdir -p "$STATE_ROOT"
if ! mkdir "$state_dir"; then
    echo "client state already exists: $state_dir" >&2
    echo "run client-cleanup.sh before starting another tunnel" >&2
    exit 1
fi

trap 'status=$?; trap - 0 HUP INT TERM; "$script_dir/client-cleanup.sh" || :; exit "$status"' 0
trap 'exit 1' HUP INT TERM

printf '%s\n' "$REMOTE_IP" > "$state_dir/remote-ip"
ip -4 route show table main default > "$state_dir/default-routes"
if [ ! -s "$state_dir/default-routes" ]; then
    echo "failed to obtain the default IPv4 route" >&2
    exit 1
fi
ip -4 route show table main exact "$REMOTE_IP/32" > "$state_dir/remote-routes"

route_info=$(ip -4 route get "$REMOTE_IP")
remote_gateway=
remote_device=
remote_source=
set -- $route_info
while [ "$#" -gt 0 ]; do
    case "$1" in
        via)
            [ "$#" -ge 2 ] || break
            remote_gateway=$2
            shift 2
            ;;
        dev)
            [ "$#" -ge 2 ] || break
            remote_device=$2
            shift 2
            ;;
        src)
            [ "$#" -ge 2 ] || break
            remote_source=$2
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

if [ -z "$remote_device" ]; then
    echo "failed to determine the route to $REMOTE_IP" >&2
    exit 1
fi

: > "$state_dir/active"

ip link set dev "$TUN_NAME" up
ip -4 address replace "$CLIENT_TUN_IP" peer "$SERVER_TUN_IP/32" dev "$TUN_NAME"

set -- "$REMOTE_IP/32" table main
if [ -n "$remote_gateway" ]; then
    set -- "$@" via "$remote_gateway"
fi
set -- "$@" dev "$remote_device"
if [ -n "$remote_source" ]; then
    set -- "$@" src "$remote_source"
fi
ip -4 route replace "$@"

ip -4 route flush table main default
ip -4 route add default via "$SERVER_TUN_IP" dev "$TUN_NAME"

trap - 0 HUP INT TERM
