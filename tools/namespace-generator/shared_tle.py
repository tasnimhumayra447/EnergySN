import json
from datetime import datetime, timedelta
from tle_generator import generate_tle

sat, _ = generate_tle(1, 1, 0, 0, 90, 1, 1 / 13.1507)
_, tle1, tle2 = sat[0]

yy, doy = int(tle1[18:20]), float(tle1[20:32])
epoch = datetime(2000 + yy if yy < 57 else 1900 + yy, 1, 1) + timedelta(days=doy - 1)

json.dump({"tle1": tle1, "tle2": tle2, "epoch": epoch.isoformat()}, open("shared_tle.json", "w"), indent=2)
print("TLE epoch (use as SIM_START):", epoch.isoformat())