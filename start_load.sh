#!/bin/bash
T=${TARGET_PCT:-60}
TARGETS=("$@")
[ ${#TARGETS[@]} -eq 0 ] && TARGETS=($(docker ps --format '{{.Names}}' | grep '^Satellite'))

for C in "${TARGETS[@]}"; do
  docker exec -d $C setsid sh -c "echo \$\$ > /tmp/nc.pgid; read q p < /sys/fs/cgroup/cpu.max; exec stress-ng --cpu 1 --cpu-load \$(( $T * q / p )) --timeout 0"
  echo "load started in $C (target $T% of cap)"
done

touch /tmp/sim_go
