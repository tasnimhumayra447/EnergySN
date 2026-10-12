from influxdb_client import InfluxDBClient

client = InfluxDBClient(url="http://localhost:8086", token="1145141919810", org="satellite_emulator")
query_api = client.query_api()

query = '''
from(bucket: "monitor")
  |> range(start: -10m)
  |> filter(fn: (r) => r._measurement == "instance_performance")
  |> limit(n: 50)
'''
result = query_api.query(org="satellite_emulator", query=query)

print("Instance Performance Data:")
print("-" * 80)
for table in result:
    for record in table.records:
        print(f"Instance: {record.tags.get('instance_id')}, Field: {record.field}, Value: {record.get_value()}, Time: {record.get_time()}")
