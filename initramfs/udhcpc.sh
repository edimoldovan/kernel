#!/bin/sh
# udhcpc script for init-net: address and default route from the lease.
case "$1" in
bound|renew)
	ip addr flush dev "$interface"
	ip addr add "$ip/${mask:-24}" dev "$interface"
	[ -n "$router" ] && ip route replace default via "${router%% *}" dev "$interface"
	;;
esac
