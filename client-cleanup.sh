#!/bin/sh

set -u
set -f
echo "$0 running:"
set -x

STATE_ROOT=${IPUDP_STATE_DIR:-/run/ipudp}

: "${TUN_NAME:?TUN_NAME is required}"

case "$TUN_NAME" in
    *[!A-Za-z0-9_.-]*)
        echo "unsupported TUN device name: $TUN_NAME" >&2
        exit 1
        ;;
esac

state_dir="$STATE_ROOT/client-$TUN_NAME"
if [ ! -d "$state_dir" ]; then
    exit 0
fi

if [ ! -f "$state_dir/active" ]; then
    rm -f "$state_dir/remote-ip" "$state_dir/default-routes" \
        "$state_dir/remote-routes"
    rmdir "$state_dir" 2>/dev/null || :
    rmdir "$STATE_ROOT" 2>/dev/null || :
    exit 0
fi

status=0

restore_routes() {
    route_file=$1
    while IFS= read -r route; do
        if [ -n "$route" ]; then
            # Word splitting is required because `ip route show` emits arguments.
            ip -4 route add $route || status=1
        fi
    done < "$route_file"
}

ip -4 route flush table main default || status=1
restore_routes "$state_dir/default-routes"

remote_ip=$(sed -n '1p' "$state_dir/remote-ip")
ip -4 route del "$remote_ip/32" table main 2>/dev/null || :
restore_routes "$state_dir/remote-routes"

if ip link show dev "$TUN_NAME" >/dev/null 2>&1; then
    ip -4 address flush dev "$TUN_NAME" || status=1
    ip link set dev "$TUN_NAME" down || status=1
fi

if [ "$status" -eq 0 ]; then
    rm -f "$state_dir/active" "$state_dir/remote-ip" \
        "$state_dir/default-routes" "$state_dir/remote-routes"
    rmdir "$state_dir" 2>/dev/null || :
    rmdir "$STATE_ROOT" 2>/dev/null || :
else
    echo "client cleanup incomplete; state retained in $state_dir" >&2
fi

exit "$status"
