# make_power_sweep.py: 9 satellites, same orbit and phase, different power specs
import random
import json
from tle_generator import generate_tle
from type_model_def import TopologyInstance, TopologyConfig, TopologyLink
from instance_types import (
    EX_TLE0_KEY, EX_TLE1_KEY, EX_TLE2_KEY, EX_ORBIT_INDEX, EX_SATELLITE_INDEX, EX_AREA_KEY,
    EX_PANEL_AREA_KEY, EX_CELL_EFFICIENCY_KEY, EX_SYSTEM_EFFICIENCY_KEY, EX_IDLE_POWER_KEY,
    EX_MAX_POWER_KEY, EX_BATTERY_CAPACITY_WH_KEY, EX_BATTERY_THRESHOLD_PERCENT_KEY,
    EX_SENSOR_POWER_KEY, EX_ALPHA_DVFS_KEY, EX_MAX_FREQUENCY_KEY, EX_BANDWIDTH_KEY,
    EX_CHANNEL_GAIN_RATIO_KEY, EX_LATITUDE_KEY, EX_LONGITUDE_KEY, EX_ALTITUDE_KEY,
    EX_GROUND_INDEX, TYPE_GROUND_STATION, TYPE_SATELLITE,
)

BASE = {  # 6U baseline
    EX_PANEL_AREA_KEY: "0.059", EX_CELL_EFFICIENCY_KEY: "0.29", EX_SYSTEM_EFFICIENCY_KEY: "0.90",
    EX_IDLE_POWER_KEY: "4.0", EX_MAX_POWER_KEY: "20.0",
    EX_BATTERY_CAPACITY_WH_KEY: "30.0", EX_BATTERY_THRESHOLD_PERCENT_KEY: "10.0",
    EX_SENSOR_POWER_KEY: "2.0", EX_ALPHA_DVFS_KEY: "6.46e-27", EX_MAX_FREQUENCY_KEY: "9.18e8",
    EX_BANDWIDTH_KEY: "1e6", EX_CHANNEL_GAIN_RATIO_KEY: "17.5",
}
VARIANTS = [
    ("baseline", {}),
    ("panel_0.03", {EX_PANEL_AREA_KEY: "0.03"}),   ("panel_0.12", {EX_PANEL_AREA_KEY: "0.12"}),
    ("battery_15", {EX_BATTERY_CAPACITY_WH_KEY: "15.0"}), ("battery_99", {EX_BATTERY_CAPACITY_WH_KEY: "99.0"}),
    ("idle_2", {EX_IDLE_POWER_KEY: "2.0"}),        ("idle_8", {EX_IDLE_POWER_KEY: "8.0"}),
    ("eff_0.20", {EX_CELL_EFFICIENCY_KEY: "0.20"}), ("eff_0.34", {EX_CELL_EFFICIENCY_KEY: "0.34"}),
]

sat, _ = generate_tle(1, 1, 0, 0, 90, 1, 1 / 13.1507)
_, tle1, tle2 = sat[0]          # identical orbit and phase for every satellite

config = TopologyConfig()
names = {} 

for i, (name, override) in enumerate(VARIANTS):
    extra = {EX_TLE0_KEY: "SWEEP_%d" % i, EX_TLE1_KEY: tle1, EX_TLE2_KEY: tle2,
             EX_AREA_KEY: "0.0.0.0", EX_ORBIT_INDEX: "0", EX_SATELLITE_INDEX: str(i),
             **BASE, **override}
    config.instances.append(TopologyInstance(TYPE_SATELLITE, extra))
    names[str(i)] = name
    print("SatelliteIndex", i, "=", name)     # keep this list for plotting

with open("sweep_variants.json", "w") as f:
    json.dump(names, f)

for index in range(2):
    config.instances.append(TopologyInstance(TYPE_GROUND_STATION, {
        EX_GROUND_INDEX: str(index),
        EX_LATITUDE_KEY: str(random.random() * 180 - 90),
        EX_LONGITUDE_KEY: str(random.random() * 360 - 180),
        EX_ALTITUDE_KEY: str(random.random() * 10)}))

with open("topology_config_power_sweep.json", "w") as f:
    f.write(config.toJson())