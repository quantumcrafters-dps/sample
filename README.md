# 🛰️ Adaptive Failsafe Router

> **Hackathon Theme — "Nexus of Code"**  
> Reality is collapsing. Legacy routing systems are offline. This failsafe is your last line of defence.

## What It Does

Takes two GPS coordinates, downloads the **real street network** from OpenStreetMap, **dynamically selects** the optimal pathfinding algorithm, computes the emergency route, and renders it on a **dark-themed interactive map**.

| Distance         | Zone              | Algorithm Selected           |
|------------------|-------------------|------------------------------|
| < 2 km           | Localized Safe    | Breadth-First Search (BFS)   |
| ≥ 2 km           | Corrupted Zone    | A* with Haversine heuristic  |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the router (uses default London coordinates)
python failsafe_router.py

# 3. Open the generated map
start nexus_route.html        # Windows
open nexus_route.html         # macOS
xdg-open nexus_route.html     # Linux
```

## Customising Coordinates

Edit the constants near the top of `failsafe_router.py`:

```python
START_COORDS = (51.5074, -0.1278)   # (latitude, longitude)
END_COORDS   = (51.5007, -0.1246)
```

There's also a commented-out pair for testing A* (≈ 5 km apart).

## Project Structure

```
├── failsafe_router.py   # Main script — routing engine + visualisation
├── requirements.txt     # Python dependencies
├── README.md            # You are here
└── nexus_route.html     # Generated after running (interactive map)
```

## Dependencies

| Package    | Purpose                                     |
|------------|---------------------------------------------|
| `osmnx`    | Downloads real street graphs from OSM       |
| `networkx` | Graph data structures & A* implementation   |
| `folium`   | Renders interactive Leaflet.js maps         |

## How the Algorithm Switch Works

1. The **Haversine formula** computes the straight-line (great-circle) distance between start and end.
2. If the distance is **under 2 km**, the graph is small enough that **BFS** — which explores every neighbour equally — finds the route quickly.
3. If the distance is **2 km or more**, the graph is too large for brute-force search. **A\*** uses the Haversine distance as a heuristic to steer toward the goal, skipping dead-end streets and finishing orders of magnitude faster.

## Sample Terminal Output

```
╔════════════════════════════════════════════════════════════════╗
║              ADAPTIVE FAILSAFE ROUTER v1.0                    ║
║          [ Reality Integrity: COMPROMISED ]                   ║
╚════════════════════════════════════════════════════════════════╝

  [SYSTEM] FAILSAFE PROTOCOL INITIATED
  [DATA]   Origin GPS     : (51.5074, -0.1278)
  [DATA]   Destination GPS: (51.5007, -0.1246)
  ──────────────────────────────────────────────────────────────
  [SYSTEM] Distance < 2.0 km. LOCALIZED SAFE ZONE detected.
  [SYSTEM] >> Breadth-First Search (BFS) Engaged.
  ──────────────────────────────────────────────────────────────
  [DATA]   Algorithm deployed : BFS
  [DATA]   Execution time    : 0.003412 s  (3.412 ms)
  ──────────────────────────────────────────────────────────────
  [✔  OK ] Interactive map saved → nexus_route.html
```

## License

Built for the **Nexus of Code** hackathon. Free to use, modify, and distribute.
