# Python-side mirror of the Go SolarInput struct
# Python writes the SolarInput, and Go reads it.
# Both sides must agree on the same etcd key structure and the same JSON field names

import json

class SolarInput:
    """
    Mirrors opensn/model/position.py's Position class exactly in shape and
    usage — a small data container with to/from JSON helpers, used the same
    way Position is: computed each tick in main.py, pushed to etcd, read
    back by the Go daemon's PowerModule.
    """
    def __init__(self, sun_angle_rad: float = 0.0, utilization: float = 0.0, timestamp: float = 0.0,
                 has_ground_contact: bool = False, tx_rate_bps: float = 0.0):
        self.sun_angle_rad = sun_angle_rad
        self.utilization = utilization
        self.timestamp = timestamp        # unix time (seconds) when this was computed
        self.has_ground_contact = has_ground_contact   # True if a ground station link is up
        self.tx_rate_bps = tx_rate_bps                 # measured downlink rate in BITS per second


def solar_input_to_json(solar_input: SolarInput) -> str:
    return json.dumps({
        "sun_angle_rad": solar_input.sun_angle_rad,
        "utilization": solar_input.utilization,
        "timestamp": solar_input.timestamp,
        "has_ground_contact": solar_input.has_ground_contact,
        "tx_rate_bps": solar_input.tx_rate_bps,
    })


def solar_input_from_json(val) -> SolarInput:
    data = json.loads(val)
    return SolarInput(
        sun_angle_rad=data.get("sun_angle_rad", 0.0),
        utilization=data.get("utilization", 0.0),
        timestamp=data.get("timestamp", 0.0),
        has_ground_contact=data.get("has_ground_contact", False),
        tx_rate_bps=data.get("tx_rate_bps", 0.0),
    )