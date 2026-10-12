
import math
import ephem
import datetime
from opensn.const.const_var import R_EARTH,LIGHT_SPEED_M_S
from opensn.model.position import Position
from instance_types import TYPE_SATELLITE,TYPE_GROUND_STATION
from instance_types import EX_TLE0_KEY,EX_TLE1_KEY,EX_TLE2_KEY,EX_LATITUDE_KEY,EX_LONGITUDE_KEY,EX_ALTITUDE_KEY
from opensn.model.instance import Instance

def deg2rad(deg: float) -> float:
    return deg / 180 * math.pi

def calculate_postion(instance: Instance,time:datetime.datetime) -> Position:
    ret = Position()
    if instance.type == TYPE_SATELLITE and instance.start:
        ephem_time = ephem.Date(time)
        ephem_obj = ephem.readtle(
            instance.extra[EX_TLE0_KEY],
            instance.extra[EX_TLE1_KEY],
            instance.extra[EX_TLE2_KEY],
        )
        ephem_obj.compute(ephem_time)
        ret.latitude = ephem_obj.sublat
        ret.longitude = ephem_obj.sublong
        ret.altitude = ephem_obj.elevation
    elif instance.type == TYPE_GROUND_STATION:
        ret.latitude = deg2rad(float(instance.extra[EX_LATITUDE_KEY]))
        ret.longitude = deg2rad(float(instance.extra[EX_LONGITUDE_KEY]))
        ret.altitude = deg2rad(float(instance.extra[EX_ALTITUDE_KEY]))
    return ret

def distance_meter(one:Position,another:Position) -> float: # meter
    z1 = (one.altitude+R_EARTH) * math.sin(one.latitude)
    base1 = (one.altitude+R_EARTH) * math.cos(one.latitude)
    x1 = base1 * math.cos(one.longitude)
    y1 = base1 * math.sin(one.longitude)
    z2 = (another.altitude+R_EARTH) * math.sin(another.latitude)
    base2 = (another.altitude+R_EARTH) * math.cos(another.latitude)
    x2 = base2 * math.cos(another.longitude)
    y2 = base2 * math.sin(another.longitude)
    return math.sqrt((x1-x2)**2+(y1-y2)**2+(z1-z2)**2)

def get_propagation_delay_s(distance_meter:float) -> float: # second
    return distance_meter / LIGHT_SPEED_M_S

def select_closest_satellite(
        ground_station:Instance,
        position_map:dict[str,Position],
        instance_map:dict[str,Instance]
    ) -> (str,bool) :
    closet_distance = math.inf
    select_satellite_id = ""
    change = True
    for instance_id,instance_info in instance_map.items():
        if instance_info.type != TYPE_SATELLITE:
            continue
        new_distance = distance_meter(
            position_map[instance_id],
            position_map[ground_station.instance_id],
        )
        if new_distance < closet_distance:
            closet_distance = new_distance
            select_satellite_id = instance_id
    if len(ground_station.connections) < 0 and select_satellite_id == "":
        return "",False
    
    for end_info in ground_station.connections.values():
        if select_satellite_id == end_info.instance_id:
            change = False
    return select_satellite_id,change

""" MY EXTENSION:
Use the satellite's existing TLE and the simulation time with PyEphem to determine
the Sun's altitude from the satellite's location, then convert that altitude into gamma """
def calculate_sun_angle(instance_info, ephem_time) -> float:
    # Find the satellite's TLE from the instance_info and create a PyEphem satellite object
    # TLE = a set of numbers describing the satellite's orbit (speed, time etc).
    sat = ephem.readtle(
        instance_info.extra[EX_TLE0_KEY],
        instance_info.extra[EX_TLE1_KEY],
        instance_info.extra[EX_TLE2_KEY],
    )

    # Compute the satellite's position at the given time
    sat.compute(ephem_time)

    # Is it in eclipse?
    if sat.eclipsed:
        return math.pi / 2   # 90 degrees means no sunlight

    # satellite's distance from Earth's centre, altitude + earth radius
    r_sat = R_EARTH + sat.elevation

    # Satellite position vector, Earth-centered and Earth-fixed 
    # (coordinate system rotates with the Earth), in meters
    sat_vec = (
        r_sat * math.cos(sat.sublat) * math.cos(sat.sublong),
        r_sat * math.cos(sat.sublat) * math.sin(sat.sublong),
        r_sat * math.sin(sat.sublat),
    )

    # create a sun object and compute its position at the given time
    sun = ephem.Sun()
    sun.compute(ephem_time)

    # Sun position. ephem's ra/dec are in the inertial frame, but sublat/sublong
    # above are Earth-fixed, so subtract Greenwich sidereal time to put the Sun
    # in the same Earth-fixed frame.

    # Basically, convert Sun's position to Earth-fixed coordinates
    # So the Sun and satellite are are in the same coordinate system
    greenwich = ephem.Observer()
    greenwich.lon = '0'
    greenwich.lat = '0'
    greenwich.date = ephem_time
    sun_ra_fixed = sun.g_ra - greenwich.sidereal_time()

    AU_M = 149597870700.0   # meters, same unit as R_EARTH
    r_sun = sun.earth_distance * AU_M
    sun_vec_geo = (
        r_sun * math.cos(sun.g_dec) * math.cos(sun_ra_fixed),
        r_sun * math.cos(sun.g_dec) * math.sin(sun_ra_fixed),
        r_sun * math.sin(sun.g_dec),
    )

    # Direction from satellite to sun
    sun_vec = tuple(s - p for s, p in zip(sun_vec_geo, sat_vec))

    dot = sum(a * b for a, b in zip(sat_vec, sun_vec))
    mag_sat = math.sqrt(sum(a * a for a in sat_vec))
    mag_sun = math.sqrt(sum(a * a for a in sun_vec))

    cos_gamma = dot / (mag_sat * mag_sun)
    cos_gamma = max(-1.0, min(1.0, cos_gamma))

    return math.acos(cos_gamma)
