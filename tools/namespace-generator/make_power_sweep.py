
# make_power_sweep.py
# Nine satellites: one baseline and eight one-factor-at-a-time variants.
# All satellites share identical orbital elements and phase.

import json
import random

from tle_generator import generate_tle
from type_model_def import TopologyInstance, TopologyConfig
from instance_types import (
    EX_TLE0_KEY, EX_TLE1_KEY, EX_TLE2_KEY,
    EX_ORBIT_INDEX, EX_SATELLITE_INDEX, EX_AREA_KEY,
    EX_PANEL_AREA_KEY, EX_CELL_EFFICIENCY_KEY,
    EX_SYSTEM_EFFICIENCY_KEY, EX_IDLE_POWER_KEY,
    EX_MAX_POWER_KEY, EX_BATTERY_CAPACITY_WH_KEY,
    EX_BATTERY_THRESHOLD_PERCENT_KEY, EX_SENSOR_POWER_KEY,
    EX_ALPHA_DVFS_KEY, EX_MIN_FREQUENCY_KEY,
    EX_MAX_FREQUENCY_KEY, EX_STATIC_POWER_KEY,
    EX_BANDWIDTH_KEY, EX_CHANNEL_GAIN_RATIO_KEY,
    EX_LATITUDE_KEY, EX_LONGITUDE_KEY, EX_ALTITUDE_KEY,
    EX_GROUND_INDEX, TYPE_GROUND_STATION, TYPE_SATELLITE,
)

# Finalized baseline parameters.
BASE = {
    EX_PANEL_AREA_KEY: "0.06",
    EX_CELL_EFFICIENCY_KEY: "0.30",
    EX_SYSTEM_EFFICIENCY_KEY: "0.90",

    EX_IDLE_POWER_KEY: "2.0",
    EX_SENSOR_POWER_KEY: "5.0",
    EX_MAX_POWER_KEY: "20.0",

    EX_BATTERY_CAPACITY_WH_KEY: "30.0",
    EX_BATTERY_THRESHOLD_PERCENT_KEY: "10.0",

    EX_ALPHA_DVFS_KEY: "2.84e-27",
    EX_STATIC_POWER_KEY: "1.1",
    EX_MIN_FREQUENCY_KEY: "1.02e8",
    EX_MAX_FREQUENCY_KEY: "9.18e8",

    EX_BANDWIDTH_KEY: "1.6e5",
    EX_CHANNEL_GAIN_RATIO_KEY: "17.5",
}

# Baseline plus two levels for each of four parameters.
# Each variant changes exactly one parameter relative to BASE.
VARIANTS = [
    ("baseline", {}),

    # Solar panel area: half and double the baseline.
    ("panel_0.03", {
        EX_PANEL_AREA_KEY: "0.03",
    }),
    ("panel_0.12", {
        EX_PANEL_AREA_KEY: "0.12",
    }),

    # Battery capacity: 50% below and 50% above the baseline.
    ("battery_15", {
        EX_BATTERY_CAPACITY_WH_KEY: "15.0",
    }),
    ("battery_45", {
        EX_BATTERY_CAPACITY_WH_KEY: "45.0",
    }),

    # Idle power: lower and higher platform power consumption.
    ("idle_1", {
        EX_IDLE_POWER_KEY: "1.0",
    }),
    ("idle_4", {
        EX_IDLE_POWER_KEY: "4.0",
    }),

    # Solar-cell efficiency: below and above the baseline.
    ("eff_0.25", {
        EX_CELL_EFFICIENCY_KEY: "0.25",
    }),
    ("eff_0.35", {
        EX_CELL_EFFICIENCY_KEY: "0.35",
    }),
]

assert len(VARIANTS) == 9
assert len({name for name, _ in VARIANTS}) == len(VARIANTS)

# Generate one set of orbital elements and reuse them for every satellite.
sat, _ = generate_tle(
    1, 1,
    0, 0,
    90,
    1,
    1 / 13.1507,
)
_, tle1, tle2 = sat[0]

config = TopologyConfig()
names = {}

for i, (name, override) in enumerate(VARIANTS):
    extra = {
        EX_TLE0_KEY: f"SWEEP_{i}",
        EX_TLE1_KEY: tle1,
        EX_TLE2_KEY: tle2,
        EX_AREA_KEY: "0.0.0.0",
        EX_ORBIT_INDEX: "0",
        EX_SATELLITE_INDEX: str(i),
        **BASE,
        **override,
    }

    config.instances.append(
        TopologyInstance(TYPE_SATELLITE, extra)
    )

    names[str(i)] = name
    print(f"SatelliteIndex {i} = {name}")

# Save satellite-index mapping for plotting and analysis.
with open("sweep_variants.json", "w") as f:
    json.dump(names, f, indent=2)

# Use a local seeded RNG so station locations are reproducible.
rng = random.Random(42)

for index in range(2):
    ground_station = {
        EX_GROUND_INDEX: str(index),
        EX_LATITUDE_KEY: str(rng.uniform(-90, 90)),
        EX_LONGITUDE_KEY: str(rng.uniform(-180, 180)),
        EX_ALTITUDE_KEY: str(rng.uniform(0, 10)),
    }

    config.instances.append(
        TopologyInstance(TYPE_GROUND_STATION, ground_station)
    )

with open("topology_config_power_sweep.json", "w") as f:
    f.write(config.toJson())

print("Wrote topology_config_power_sweep.json")
print("Wrote sweep_variants.json")
