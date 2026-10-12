from opensn.operator.emulator_operator import EmulatorOperator
from opensn.model.instance import Instance
# me:
from opensn.model.solar_input import SolarInput

#them:
from opensn.model.position import Position
from opensn.const.dict_fields import PARAMETER_KEY_CONNECT,PARAMETER_KEY_DELAY,PARAMETER_KEY_BANDWIDTH,PARAMETER_KEY_LOSS
from opensn.model.link import LinkBase
from opensn.utils.tools import dec2ra
from config import ADDR,PORT
from datetime import datetime
from trajectory import calculate_postion,distance_meter,select_closest_satellite,get_propagation_delay_s
from instance_types import TYPE_GROUND_STATION, TYPE_SATELLITE, EX_ORBIT_INDEX,EX_ALTITUDE_KEY,EX_LATITUDE_KEY,EX_LONGITUDE_KEY, EX_AREA_KEY, EX_SATELLITE_INDEX
from address_type import LINK_V4_ADDR_KEY
from time import sleep
from address_allocator import alloc_ipv4,format_ipv4
from loguru import logger

# my code:
from trajectory import calculate_postion,distance_meter, select_closest_satellite, get_propagation_delay_s, calculate_sun_angle
import json, math, time
from influxdb_client import InfluxDBClient

# simulation updates every 5 seconds
step_second = 5

polar_threshold = dec2ra(66.5)

# InfluxDB configuration
influxdb_url = "http://localhost:8086"  # Adjust based on your config
influxdb_token = "1145141919810"  # Token from custom-influxdb Dockerfile
influxdb_org = "satellite_emulator"  # Org from custom-influxdb Dockerfile
influxdb_bucket = "monitor"  # Bucket from custom-influxdb Dockerfile

# Initialize InfluxDB client (will be created once in main)
influxdb_client = None
query_api = None

def genenrate_config(cli:EmulatorOperator,node_index:int,instance_id:str):
    instance_info = cli.get_instance(node_index,instance_id)

    # Creates a dictionary (config_map) to store routing and link data for a specific node.
    # If it's a satellite, it adds its specific geographical "area".
    config_map = {
        "instance_id": instance_id,
        "link_infos": {},
        "end_infos": {},
    }
    if instance_info.type == TYPE_SATELLITE:
        config_map['area'] = instance_info.extra[EX_AREA_KEY]
        
    for k,v in (instance_info.connections or {}).items():
        instance_index = -1
        link_info = cli.get_link(node_index,k)
        for end_index in range(len(link_info.end_infos)):
            if link_info.end_infos[end_index].instance_id == instance_id:
                instance_index = end_index
        if instance_index < 0:
            return {}
        another_instance_info = cli.get_instance(link_info.end_infos[1-instance_index].end_node_index,link_info.end_infos[1-instance_index].instance_id)
        config_map["link_infos"][k] = link_info.address_infos[instance_index]
        config_map["end_infos"][k] = {
            "instance_id": v.instance_id,
            "type": v.instance_type,
        }
        if another_instance_info.type == TYPE_SATELLITE:
            config_map["end_infos"][k]['area'] = another_instance_info.extra[EX_AREA_KEY]
    return config_map

def init_influxdb_client():
    """
    Initialize InfluxDB client for querying CPU usage metrics
    """
    global influxdb_client, query_api
    try:
        influxdb_client = InfluxDBClient(url=influxdb_url, token=influxdb_token, org=influxdb_org)
        query_api = influxdb_client.query_api()
        logger.info("InfluxDB client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize InfluxDB client: {e}")
        influxdb_client = None
        query_api = None

def get_all_utilizations() -> dict[str, float]:
    """Fetch latest CPUUsage for ALL instances in one query instead of N."""
    if query_api is None:
        return {}
    try:
        query = f'''
        from(bucket: "{influxdb_bucket}")
            |> range(start: -3m)
            |> filter(fn: (r) => r._measurement == "instance_performance")
            |> filter(fn: (r) => r._field == "CPUUsage")
            |> group(columns: ["instance_id"])
            |> mean()
        '''
        result = query_api.query(org=influxdb_org, query=query)
        out = {}
        for table in result:
            for record in table.records:
                out[record.values.get("instance_id")] = max(0.0, float(record.get_value()))
        return out
    except Exception as e:
        logger.warning(f"Failed to batch-query CPU usage: {e}")
        return {}

def get_link_tx_rates(link_ids: list[str]) -> dict[str, float]:
    """Latest SendBps for the given links in one query, returned in bits/s."""
    if query_api is None or len(link_ids) == 0:
        return {}
    try:
        link_set = "[" + ",".join(f'"{l}"' for l in link_ids) + "]"
        query = f'''
        from(bucket: "{influxdb_bucket}")
            |> range(start: -1m)
            |> filter(fn: (r) => r._measurement == "link_performance")
            |> filter(fn: (r) => r._field == "SendBps")
            |> filter(fn: (r) => contains(value: r.link_id, set: {link_set}))
            |> group(columns: ["link_id"])
            |> last()
        '''
        result = query_api.query(org=influxdb_org, query=query)
        out = {}
        for table in result:
            for record in table.records:
                # monitor module stores bytes/s, the power model wants bits/s
                out[record.values.get("link_id")] = max(0.0, float(record.get_value())) * 8
        return out
    except Exception as e:
        logger.warning(f"Failed to batch-query link tx rates: {e}")
        return {}

if __name__ == "__main__":

    instance_config_updated:dict[str,str] = {}
    
    cli = EmulatorOperator(ADDR,PORT)
    
    # Initialize InfluxDB client for querying CPU metrics
    init_influxdb_client()

    # Initial delay to allow daemon to process topology
    logger.info("Waiting for topology to be processed...")
    sleep(3)
    
    # Generate and push ALL configs immediately on startup
    # This prevents race conditions between topology upload and container creation
    logger.info("Pre-generating all instance configs...")
    node_list = cli.get_node_map()
    all_instances = {}
    for node_index in node_list.keys():
        instance_map = cli.get_instance_map(node_index)
        all_instances.update(instance_map)
    
    for instance_id, instance_info in all_instances.items():
        try:
            config_map = genenrate_config(cli, instance_info.node_index, instance_id)
            cli.put_instance_config(instance_info.node_index, instance_id, json.dumps(config_map))
            instance_config_updated[instance_id] = json.dumps(config_map)
            logger.info(f"Pre-generated config for {instance_id}")
        except Exception as e:
            logger.warning(f"Failed to pre-generate config for {instance_id}: {e}")
    
    logger.info("Waiting for config files to be written to disk...")
    sleep(2)
    
    # Start all instances that were created but not yet running
    logger.info("Starting instances...")
    for instance_id, instance_info in all_instances.items():
        if not instance_info.start:
            try:
                instance_info.start = True
                cli.put_instance(instance_info)
                logger.info(f"Started instance {instance_id}")
            except Exception as e:
                logger.warning(f"Failed to start instance {instance_id}: {e}")
    
    logger.info("Waiting for containers to start...")
    sleep(3)

    # Create Emulator Operator
    while True:
        loop_start = time.time()
        node_list = cli.get_node_map()
        all_instance_map: dict[str,Instance] = {}
        node_link_map: dict[int,dict[str,LinkBase]] = {}
        ground_station_list:list[Instance] = []
        for node_index,node in node_list.items():
            instance_map = cli.get_instance_map(node_index)
            for instance_id,instance in instance_map.items():
                all_instance_map[instance_id] = instance
                if instance.type == TYPE_GROUND_STATION:
                    ground_station_list.append(instance)
                    gs_position = Position()
                    gs_position.latitude = float(instance.extra[EX_LATITUDE_KEY]) / 180 * math.pi
                    gs_position.longitude = float(instance.extra[EX_LONGITUDE_KEY]) / 180 * math.pi
                    gs_position.altitude = float(instance.extra[EX_ALTITUDE_KEY])
                    cli.put_position(instance_id,gs_position)

        address_map = {}
        for node_index,node in node_list.items():
            node_link_map[node_index] = {}
            link_map = cli.get_link_map(node_index)
            for link_id,link_info in link_map.items():
                addr0 = link_info.address_infos[0] or {}
                addr1 = link_info.address_infos[1] or {}
                if LINK_V4_ADDR_KEY not in addr0 or LINK_V4_ADDR_KEY not in addr1:
#                if LINK_V4_ADDR_KEY not in link_info.address_infos[0] or \
#                    LINK_V4_ADDR_KEY not in link_info.address_infos[1] is None:
                    if link_id not in address_map.keys():
                        address_map[link_id] = alloc_ipv4(30)
                    
                    subnet = address_map[link_id]
                    link_info.address_infos = [{
                        LINK_V4_ADDR_KEY: format_ipv4(subnet[1],30)
                    },
                    {
                        LINK_V4_ADDR_KEY: format_ipv4(subnet[2],30)
                    }]
                    cli.put_link(link_info)
                node_link_map[node_index][link_id] = link_info
                

        position_map: dict[str,Position] = {"":Position()}
        time_now = datetime.now()
        utilizations = get_all_utilizations()   # NEW: one query for everyone, not one per satellite
        for instance_id,instance_info in all_instance_map.items():
            if instance_info.start:
                new_postion = calculate_postion(instance_info,time_now)
                cli.put_position(instance_id,new_postion)

            else:
                new_postion = Position()
            position_map[instance_id] = new_postion
        # Do Ground Station Reconnect
    
        
        for ground_station in ground_station_list:
            if not ground_station.start:
                continue
            gs_position = position_map[ground_station.instance_id]
            satellite_id,change = select_closest_satellite(
                ground_station,
                position_map,
                all_instance_map
            )
            if change:
                address1 = {}
                address2 = {}
                
                old_link_id = ""
                for key in ground_station.connections.keys():
                    old_link_id = key
                    break
                if old_link_id != "":
                    old_link = cli.disable_link_between(
                        ground_station.node_index,
                        ground_station.instance_id,
                        ground_station.connections[key].end_node_index,
                        ground_station.connections[key].instance_id
                    )
                    logger.info("Switch %s from %s to %s"%(
                        ground_station.instance_id,
                        ground_station.connections[old_link_id].instance_id,
                        satellite_id
                    ))
                    old_sat_config = genenrate_config(cli,ground_station.connections[old_link_id].end_node_index,ground_station.connections[old_link_id].instance_id)
                    cli.put_instance_config(ground_station.connections[old_link_id].end_node_index,ground_station.connections[old_link_id].instance_id,json.dumps(old_sat_config))

                    # config_map = genenrate_config(
                    #     satellite_id,all_instance_map[ground_station.connections[key].instance_id],node_link_map)
                    if len(old_link) > 0:
                        address1 = old_link[old_link_id].address_infos[0]
                        address2 = old_link[old_link_id].address_infos[1]
                else:
                    subnet = alloc_ipv4(30)
                    address1 = {LINK_V4_ADDR_KEY:format_ipv4(subnet[1],30)}
                    address2 = {LINK_V4_ADDR_KEY:format_ipv4(subnet[2],30)}
                    logger.info("Switch %s from %s to %s"%(
                        ground_station.instance_id,
                        "None",
                        satellite_id
                    ))
                cli.enable_link_between(
                    ground_station.node_index,
                    ground_station.instance_id,
                    all_instance_map[satellite_id].node_index,
                    all_instance_map[satellite_id].instance_id,
                    address_info1=address1,
                    address_info2=address2,
                )
                gs_config = genenrate_config(cli,ground_station.node_index,ground_station.instance_id)
                # print(gs_config)
                cli.put_instance_config(ground_station.node_index,ground_station.instance_id,json.dumps(gs_config))
                sat_config = genenrate_config(cli,all_instance_map[satellite_id].node_index,all_instance_map[satellite_id].instance_id)
                # print(sat_config)
                cli.put_instance_config(all_instance_map[satellite_id].node_index,all_instance_map[satellite_id].instance_id,json.dumps(sat_config))

        # My code: ground contact + measured tx rate, then write solar input.
        # A satellite is "in contact" if a started ground station's link points at it.
        ground_links: dict[str, list[str]] = {}   # satellite instance_id -> its ground link_ids
        for ground_station in ground_station_list:
            if not ground_station.start:
                continue
            for link_id, connection in (ground_station.connections or {}).items():
                ground_links.setdefault(connection.instance_id, []).append(link_id)
        all_link_ids = [l for links in ground_links.values() for l in links]
        tx_rates = get_link_tx_rates(all_link_ids)
        logger.info(f"Ground contact: {len(ground_links)} satellites, tx rates (bps): {tx_rates}")
        # Debugging line: log the satellite indices for all satellites in the instance map
        logger.info({i.instance_id: i.extra.get(EX_SATELLITE_INDEX) for i in all_instance_map.values() if i.type == TYPE_SATELLITE})

        for instance_id, instance_info in all_instance_map.items():
            if instance_info.start and instance_info.type == TYPE_SATELLITE:
                gamma = calculate_sun_angle(instance_info, time_now)
                utilization = utilizations.get(instance_id, 0.5)
                link_ids = ground_links.get(instance_id, [])
                cli.put_solar_input(instance_id, SolarInput(
                    sun_angle_rad=gamma,
                    utilization=utilization,
                    timestamp=time_now.timestamp(),
                    has_ground_contact=len(link_ids) > 0,
                    tx_rate_bps=sum(tx_rates.get(l, 0.0) for l in link_ids),
                ))

        for node_index,link_map in node_link_map.items():
            for link_id,link_info in link_map.items():
                if link_info.parameter is None:
                    link_info.parameter = {}
                # ME: 301-303
                if link_info.end_infos[0].instance_id=="" or link_info.end_infos[1].instance_id == "":
                    continue
                if link_info.end_infos[0].instance_id not in all_instance_map or \
                link_info.end_infos[1].instance_id not in all_instance_map:
                    continue   # link references an instance not present in this iteration's snapshot; skip, will retry next loop
                if not link_info.enable:
                    continue
                if link_info.end_infos[0].instance_type == TYPE_SATELLITE and \
                    link_info.end_infos[1].instance_type == TYPE_SATELLITE and \
                    all_instance_map[link_info.end_infos[1].instance_id].extra[EX_ORBIT_INDEX] != \
                    all_instance_map[link_info.end_infos[0].instance_id].extra[EX_ORBIT_INDEX] and \
                    (abs(position_map[link_info.end_infos[0].instance_id].latitude) > polar_threshold or \
                    abs(position_map[link_info.end_infos[1].instance_id].latitude) > polar_threshold):
                        # if PARAMETER_KEY_CONNECT in link_info.parameter.keys() and link_info.parameter[PARAMETER_KEY_CONNECT]==1:
                        #     logger.info("connect %s"%link_id)
                        link_info.parameter[PARAMETER_KEY_CONNECT] = 0
                else:
                    # if PARAMETER_KEY_CONNECT not in link_info.parameter.keys() or link_info.parameter[PARAMETER_KEY_CONNECT]==0:
                    #         logger.info("disconnect %s"%link_id)
                    link_info.parameter[PARAMETER_KEY_CONNECT] = 1

                if link_info.end_infos[0].instance_type == "" :
                    continue

                distance = distance_meter(
                    position_map[link_info.end_infos[0].instance_id],
                    position_map[link_info.end_infos[1].instance_id]
                )
                delay = int(get_propagation_delay_s(distance)*1000000)
                link_info.parameter[PARAMETER_KEY_DELAY] = delay
                link_info.parameter[PARAMETER_KEY_BANDWIDTH] = 1000000
                link_info.parameter[PARAMETER_KEY_LOSS] = 150
                try:
                    cli.put_link_parameter(link_info.node_index,link_info.link_id,link_info.parameter)
                except Exception as e:
                    logger.warning(f"Failed to update link parameter for {link_info.link_id}: {e}")

        # time the loop
        loop_duration = time.time() - loop_start
        logger.info(f"Loop iteration took {loop_duration:.2f}s (target: {step_second}s)")

        sleep(step_second)

