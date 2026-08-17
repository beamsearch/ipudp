#!/bin/sh

set -u
echo "$0 running:"
set -x

NFT_TABLE=ipudp
STATE_ROOT=${IPUDP_STATE_DIR:-/run/ipudp}

: "${TUN_NAME:?TUN_NAME is required}"

case "$TUN_NAME" in
    *[!A-Za-z0-9_.-]*)
        echo "unsupported TUN device name: $TUN_NAME" >&2
        exit 1
        ;;
esac

state_dir="$STATE_ROOT/server-$TUN_NAME"
if [ ! -d "$state_dir" ]; then
    exit 0
fi

if [ ! -f "$state_dir/active" ]; then
    rm -f "$state_dir/ip-forward" "$state_dir/ip-forward-changed" \
        "$state_dir/nft-table"
    rmdir "$state_dir" 2>/dev/null || :
    rmdir "$STATE_ROOT" 2>/dev/null || :
    exit 0
fi

status=0

if [ -f "$state_dir/nft-table" ]; then
    nft delete table ip "$NFT_TABLE" || status=1
fi

if ip link show dev "$TUN_NAME" >/dev/null 2>&1; then
    ip -4 address flush dev "$TUN_NAME" || status=1
    ip link set dev "$TUN_NAME" down || status=1
fi

if [ -f "$state_dir/ip-forward-changed" ]; then
    ip_forward=$(sed -n '1p' "$state_dir/ip-forward")
    case "$ip_forward" in
        0|1)
            sysctl -q -w "net.ipv4.ip_forward=$ip_forward" || status=1
            ;;
        *)
            echo "invalid saved net.ipv4.ip_forward value" >&2
            status=1
            ;;
    esac
fi

if [ "$status" -eq 0 ]; then
    rm -f "$state_dir/active" "$state_dir/ip-forward" \
        "$state_dir/ip-forward-changed" "$state_dir/nft-table"
    rmdir "$state_dir" 2>/dev/null || :
    rmdir "$STATE_ROOT" 2>/dev/null || :
else
    echo "server cleanup incomplete; state retained in $state_dir" >&2
fi

exit "$status"
