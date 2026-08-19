import osmnx as ox
import time

ox.settings.log_console = True
ox.settings.timeout = 60

# Ranchi 1km area
north, south, east, west = 23.342, 23.322, 85.312, 85.292

print("Downloading 1km bbox with network_type='drive'...")
t0 = time.time()
try:
    G = ox.graph_from_bbox(bbox=(west, south, east, north), network_type="drive")
    t1 = time.time()
    print(f"Success! Nodes: {len(G.nodes)}. Time: {t1-t0:.2f}s")
except Exception as e:
    print(f"Failed: {e}")
