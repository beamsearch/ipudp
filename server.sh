#!/bin/sh

set -eu
set -f
echo "$0 running:"
set -x

CLIENT_TUN_IP=10.0.1.1
SERVER_TUN_IP=10.0.1.2
NFT_TABLE=ipudp
STATE_ROOT=${IPUDP_STATE_DIR:-/run/ipudp}

: "${TUN_NAME:?TUN_NAME is required}"
: "${TUN_MTU:?TUN_MTU is required}"

case "$TUN_MTU" in
    *[!0-9]*)
        echo "TUN_MTU must be a decimal integer" >&2
        exit 1
        ;;
esac

for command_name in ip nft sysctl; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "$command_name is required" >&2
        exit 1
    fi
done

case "$TUN_NAME" in
    *[!A-Za-z0-9_.-]*)
        echo "unsupported TUN device name: $TUN_NAME" >&2
        exit 1
        ;;
esac

if nft list table ip "$NFT_TABLE" >/dev/null 2>&1; then
    echo "nftables table 'ip $NFT_TABLE' already exists" >&2
    exit 1
fi

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
state_dir="$STATE_ROOT/server-$TUN_NAME"

umask 077
mkdir -p "$STATE_ROOT"
if ! mkdir "$state_dir"; then
    echo "server state already exists: $state_dir" >&2
    echo "run server-cleanup.sh before starting another tunnel" >&2
    exit 1
fi

trap 'status=$?; trap - 0 HUP INT TERM; "$script_dir/server-cleanup.sh" || :; exit "$status"' 0
trap 'exit 1' HUP INT TERM

sysctl -n net.ipv4.ip_forward > "$state_dir/ip-forward"
: > "$state_dir/active"

ip link set dev "$TUN_NAME" mtu "$TUN_MTU" up
ip -4 address replace "$SERVER_TUN_IP" peer "$CLIENT_TUN_IP/32" dev "$TUN_NAME"
sysctl -q -w net.ipv4.ip_forward=1

nft -f - <<EOF
add table ip $NFT_TABLE
add chain ip $NFT_TABLE postrouting { type nat hook postrouting priority srcnat; policy accept; }
add rule ip $NFT_TABLE postrouting ip saddr $CLIENT_TUN_IP masquerade
EOF
: > "$state_dir/nft-table"

trap - 0 HUP INT TERM
