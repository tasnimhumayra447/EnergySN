#!/bin/sh
# stress5.sh: hold a constant stress level on 5 satellites for DURATION seconds

DURATION=7200     # 120 min (one full orbit)
LOW=50            # stress-ng target (% of cap) for the low group, maps to ~20-30% measured
HIGH=100          # stress-ng target for the high group, maps to ~60% measured

# container name -> stress level
SATS="
Satellite_e2f38a3b $LOW
Satellite_5c9f25e2 $LOW
Satellite_7986750f $HIGH
Satellite_8aa0da98 $HIGH
Satellite_bfc412c1 $HIGH
"

echo "$SATS" | while read name target; do
  [ -z "$name" ] && continue
  docker exec "$name" sh -c "
    read quota period < /sys/fs/cgroup/cpu.max
    scaled=\$(( $target * quota / period ))
    echo \"\$(date +%s) $name target ${target}% of cap -> stress-ng load \${scaled}%\"
    stress-ng --cpu 1 --cpu-load \$scaled --timeout ${DURATION}s
  " > "log_$name.txt" 2>&1 &
done

wait
echo "done"
