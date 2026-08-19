import osmnx as ox
import time

ox.settings.log_console = True
ox.settings.timeout = 60
ox.settings.overpass_url = "https://lz4.overpass-api.de/api"

# Ranchi 10km area
north, south, east, west = 23.4, 23.2, 85.4, 85.2

print("Downloading 10km bbox with exact custom_filter...")
t0 = time.time()
try:
    G = ox.graph_from_bbox(
        bbox=(west, south, east, north),
        network_type="all_private", 
        custom_filter='["highway"~"motorway|trunk|primary|secondary"]'
    )
    t1 = time.time()
    print(f"Success! Nodes: {len(G.nodes)}. Time: {t1-t0:.2f}s")
except Exception as e:
    print(f"Failed: {e}")
