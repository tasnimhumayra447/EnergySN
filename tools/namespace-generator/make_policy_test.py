import json
from type_model_def import TopologyInstance, TopologyConfig
from instance_types import (
    EX_TLE0_KEY, EX_TLE1_KEY, EX_TLE2_KEY, EX_ORBIT_INDEX, EX_SATELLITE_INDEX, EX_AREA_KEY,
    EX_PANEL_AREA_KEY, EX_CELL_EFFICIENCY_KEY, EX_SYSTEM_EFFICIENCY_KEY, EX_IDLE_POWER_KEY,
    EX_MAX_POWER_KEY, EX_BATTERY_CAPACITY_WH_KEY, EX_BATTERY_THRESHOLD_PERCENT_KEY,
    EX_SENSOR_POWER_KEY, EX_ALPHA_DVFS_KEY, EX_MIN_FREQUENCY_KEY, EX_MAX_FREQUENCY_KEY,
    EX_STATIC_POWER_KEY, EX_BANDWIDTH_KEY, EX_CHANNEL_GAIN_RATIO_KEY,
    EX_LATITUDE_KEY, EX_LONGITUDE_KEY, EX_ALTITUDE_KEY, EX_GROUND_INDEX,
    TYPE_GROUND_STATION, TYPE_SATELLITE, EX_POLICY_ENABLED_KEY,
)

tle = json.load(open("shared_tle.json"))

BASE = {
    EX_PANEL_AREA_KEY: "0.17", EX_CELL_EFFICIENCY_KEY: "0.30", EX_SYSTEM_EFFICIENCY_KEY: "0.90",
    EX_IDLE_POWER_KEY: "2.0", EX_SENSOR_POWER_KEY: "7.0", EX_MAX_POWER_KEY: "40.0",
    EX_BATTERY_CAPACITY_WH_KEY: "60.0", EX_BATTERY_THRESHOLD_PERCENT_KEY: "20.0",
    EX_ALPHA_DVFS_KEY: "2.84e-27", EX_STATIC_POWER_KEY: "1.0",
    EX_MIN_FREQUENCY_KEY: "3.06e8", EX_MAX_FREQUENCY_KEY: "1.50e9",
    EX_BANDWIDTH_KEY: "1.6e5", EX_CHANNEL_GAIN_RATIO_KEY: "17.5",
}
VARIANTS = [("baseline_off", "0"), ("policy_on", "1")]   # baseline first (index 0)

config, names = TopologyConfig(), {}
for i, (name, flag) in enumerate(VARIANTS):
    config.instances.append(TopologyInstance(TYPE_SATELLITE, {
        EX_TLE0_KEY: f"POLICY_{i}", EX_TLE1_KEY: tle["tle1"], EX_TLE2_KEY: tle["tle2"],
        EX_AREA_KEY: "0.0.0.0", EX_ORBIT_INDEX: "0", EX_SATELLITE_INDEX: str(i),
        **BASE, EX_POLICY_ENABLED_KEY: flag}))
    names[str(i)] = name
for index, (lat, lon) in enumerate([(30.0, 10.0), (-30.0, 100.0)]):
    config.instances.append(TopologyInstance(TYPE_GROUND_STATION, {
        EX_GROUND_INDEX: str(index), EX_LATITUDE_KEY: str(lat),
        EX_LONGITUDE_KEY: str(lon), EX_ALTITUDE_KEY: "0"}))

json.dump(names, open("policy_variants.json", "w"), indent=2)
open("topology_config_policy_test.json", "w").write(config.toJson())