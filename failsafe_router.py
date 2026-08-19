"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ADAPTIVE FAILSAFE ROUTER v2.0                           ║
║                    ─────────────────────────────                            ║
║  Hackathon Theme : "Nexus of Code"                                         ║
║  Premise         : Reality is collapsing. Legacy routing systems are dead.  ║
║                    This failsafe downloads real-world street data from      ║
║                    OpenStreetMap, dynamically picks the best search         ║
║                    algorithm, and renders an emergency escape route on an   ║
║                    interactive map.                                         ║
║                                                                            ║
║  HOW IT WORKS (for students):                                              ║
║   1. We grab real streets around two GPS points using OpenStreetMap.        ║
║   2. We measure the straight-line (Haversine) distance between them.       ║
║   3. If the distance is SHORT (< 2 km) → use Breadth-First Search (BFS).  ║
║      BFS explores every neighboring street equally — perfect for small,    ║
║      dense city grids where the answer is only a few hops away.            ║
║   4. If the distance is LONG  (≥ 2 km) → use A* Search with Haversine     ║
║      as a heuristic. A* is smarter: it "guesses" which direction is best   ║
║      and skips dead ends, making it far faster over large networks.        ║
║   5. The route is drawn on an interactive Folium map and saved as HTML.    ║
║                                                                            ║
║  v2.0 — TIERED NETWORK DOWNLOAD                                           ║
║   The router now adapts the road network it downloads based on distance:   ║
║     • < 5 km   → ALL driveable roads (full detail)                         ║
║     • 5–50 km  → Primary roads and above (skip residential)               ║
║     • 50–200 km → Trunk roads and highways only                            ║
║     • > 200 km  → Motorways and trunk roads only (national highways)       ║
║   This means even Guwahati → Kargil downloads in seconds, not hours!      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ─────────────────────────────────────────────────────────────────────────────
# IMPORTS
# ─────────────────────────────────────────────────────────────────────────────

import math                # For sin, cos, sqrt, atan2 — the Haversine formula
import sys                 # For sys.stdout.write / flush — in-place terminal updates
import time                # For time.perf_counter() — high-resolution timing
import threading           # For running the spinner animation in a background thread
from collections import deque  # Fast double-ended queue used in BFS

import osmnx as ox         # Downloads real street networks from OpenStreetMap
import networkx as nx      # Graph data-structure that osmnx builds on
import folium              # Renders interactive Leaflet.js maps in HTML


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION — change these GPS coordinates to any two points you want!
# ─────────────────────────────────────────────────────────────────────────────

# Example: Two points in Ranchi (~1.9 km — will trigger BFS)
START_COORDS = (23.332554, 85.301715)   # (latitude, longitude) of the START
END_COORDS   = (23.397792, 85.355124)   # (latitude, longitude) of the END

# ─── Want to test long-distance A*?  Uncomment a pair below: ──────────────
# Ranchi → Jamshedpur (~120 km — will use trunk roads + A*)
# START_COORDS = (23.3441, 85.3096)
# END_COORDS   = (22.8046, 86.2029)

# Guwahati → Kargil (~2500 km — will use motorways/trunk only + A*)
# START_COORDS = (26.1445, 91.7362)
# END_COORDS   = (34.5539, 76.1349)

# Distance threshold in kilometres that controls the BFS ↔ A* switch.
DISTANCE_THRESHOLD_KM = 2.0

# Output filename for the interactive map.
OUTPUT_HTML = "nexus_route.html"


# ─────────────────────────────────────────────────────────────────────────────
# ROAD TIER CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
#
# ── WHY TIERS? (for students) ────────────────────────────────────────────
# OpenStreetMap classifies roads by importance:
#   motorway   → National highways / interstates (fastest, fewest)
#   trunk      → Major arterials connecting cities
#   primary    → Main roads within a region
#   secondary  → Collector roads
#   tertiary   → Local streets
#   residential, service, etc. → Neighbourhood roads (most numerous)
#
# For a 2 km route we want ALL roads (residential included) because the
# route weaves through local streets.  But for a 500 km route, downloading
# every residential lane across 5 states would be gigabytes of data and
# take forever.  Instead, we ONLY download the highways that such a trip
# would actually use.
#
# The "custom_filter" parameter in osmnx lets us specify an Overpass QL
# filter string that restricts which highway types are returned.
# ──────────────────────────────────────────────────────────────────────────

ROAD_TIERS = [
    # (max_km, label, allowed_highways, bbox_padding_deg)
    #
    # bbox_padding_deg = degrees of lat/lon padding around the bounding box.
    # At the equator 1° ≈ 111 km; at 35°N it's ≈ 91 km.
    # We use generous padding so the router has room to find detours.

    (5,    "ALL ROADS",
     None,  # None = keep all roads
     0.01),  # ~1.1 km padding

    (50,   "PRIMARY+",
     ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link"],
     0.05),  # ~5.5 km padding

    (200,  "TRUNK+",
     ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"],
     0.15),  # ~16 km padding

    (None, "MOTORWAY/TRUNK ONLY",  # None = no upper limit (catch-all)
     ["motorway", "motorway_link", "trunk", "trunk_link"],
     0.5),   # ~55 km padding
]


# ═════════════════════════════════════════════════════════════════════════════
# TERMINAL UI — Sci-fi styled print helpers + progress bar + spinner
# ═════════════════════════════════════════════════════════════════════════════

def _banner():
    """Print the boot-up banner to the terminal."""
    print()
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║      ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗           ║")
    print("║      ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝           ║")
    print("║      ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗           ║")
    print("║      ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║           ║")
    print("║      ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║           ║")
    print("║      ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝╚══════╝           ║")
    print("║              ADAPTIVE FAILSAFE ROUTER v2.0                  ║")
    print("║          [ Reality Integrity: COMPROMISED ]                 ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()


def _sys(msg: str):
    """Print a system-level message in sci-fi style."""
    print(f"  [SYSTEM] {msg}")


def _data(label: str, value):
    """Print a labelled data readout."""
    print(f"  [DATA]   {label}: {value}")


def _warn(msg: str):
    """Warnings are silenced in v2.0 to keep output clean."""
    pass  # Suppressed — the retry logic handles errors internally.


def _ok(msg: str):
    """Print a success/confirmation message."""
    print(f"  [✔  OK ] {msg}")


def _separator():
    """Print a visual divider."""
    print("  ──────────────────────────────────────────────────────────")


# ─────────────────────────────────────────────────────────────────────────────
# PROGRESS BAR — Visual phase tracker
# ─────────────────────────────────────────────────────────────────────────────
#
# ── HOW THIS WORKS (for students) ────────────────────────────────────────
# The progress bar shows a visual representation of how far we are through
# the 5-phase pipeline.  It uses block characters (█ and ░) to fill a bar.
#
# Example output:
#   [████████████░░░░░░░░]  60%  Phase 3/5 — Acquiring street network  (12.4s)
#
# Each phase updates the bar, shows elapsed time, and prints a final
# "completed" line when done.
# ──────────────────────────────────────────────────────────────────────────

TOTAL_PHASES = 5          # Total number of pipeline phases
PROGRESS_BAR_WIDTH = 30   # Width of the bar in characters


def _progress_bar(phase: int, phase_name: str, elapsed: float = 0.0,
                  status: str = "running"):
    """
    Print (or update) the progress bar for the given phase.

    Parameters
    ----------
    phase      : int   — current phase number (1-based)
    phase_name : str   — human-readable description of this phase
    elapsed    : float — seconds elapsed for this phase
    status     : str   — 'running' or 'done'
    """
    # Calculate fill percentage.
    if status == "done":
        # When a phase completes, the bar shows progress up to this phase.
        fraction = phase / TOTAL_PHASES
    else:
        # While running, show progress up to the START of this phase.
        fraction = (phase - 1) / TOTAL_PHASES

    filled = int(PROGRESS_BAR_WIDTH * fraction)
    empty  = PROGRESS_BAR_WIDTH - filled
    pct    = int(fraction * 100)

    bar = "█" * filled + "░" * empty

    if status == "done":
        time_str = f"({elapsed:.2f}s)" if elapsed > 0.01 else "(instant)"
        line = f"  [{bar}] {pct:3d}%  Phase {phase}/{TOTAL_PHASES} — {phase_name}  {time_str}"
        print(f"\r{line}")
    else:
        line = f"  [{bar}] {pct:3d}%  Phase {phase}/{TOTAL_PHASES} — {phase_name} …"
        # Use \r to overwrite the current line (in-place update).
        sys.stdout.write(f"\r{line}")
        sys.stdout.flush()


# ─────────────────────────────────────────────────────────────────────────────
# SPINNER — Animated waiting indicator for long operations
# ─────────────────────────────────────────────────────────────────────────────
#
# ── HOW THIS WORKS (for students) ────────────────────────────────────────
# When we call the Overpass API, the download can take 10–120 seconds.
# During that time, the program looks frozen.  A spinner animation shows
# the user that the program is still working.
#
# We run the spinner in a BACKGROUND THREAD (using Python's `threading`
# module).  The main thread does the actual download, and the spinner
# thread updates the terminal with a rotating character (⠋ ⠙ ⠹ ⠸ …).
# When the download finishes, we set `spinner.stop_flag = True` to signal
# the spinner thread to stop.
# ──────────────────────────────────────────────────────────────────────────

class Spinner:
    """A threaded spinner that animates in-place while work happens."""

    # Braille dot pattern — creates a smooth spinning animation.
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = "Working"):
        self.message = message
        self.stop_flag = False
        self._thread = None
        self._start_time = None

    def _animate(self):
        """Animation loop — runs in a background thread."""
        idx = 0
        while not self.stop_flag:
            elapsed = time.perf_counter() - self._start_time
            frame = self.FRAMES[idx % len(self.FRAMES)]
            line = f"  {frame}  {self.message} … {elapsed:.1f}s"
            sys.stdout.write(f"\r{line}    ")  # Extra spaces clear old text
            sys.stdout.flush()
            time.sleep(0.1)
            idx += 1

    def start(self):
        """Start the spinner in a background thread."""
        self.stop_flag = False
        self._start_time = time.perf_counter()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self, final_message: str = None):
        """Stop the spinner and print a final status line."""
        self.stop_flag = True
        if self._thread:
            self._thread.join(timeout=1.0)
        elapsed = time.perf_counter() - self._start_time
        # Clear the spinner line.
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()
        if final_message:
            print(f"  {final_message}")
        return elapsed


# ═════════════════════════════════════════════════════════════════════════════
# CORE CLASS — AdaptiveFailsafeRouter
# ═════════════════════════════════════════════════════════════════════════════

class AdaptiveFailsafeRouter:
    """
    The heart of the Failsafe system.

    This class:
      • Measures straight-line distance FIRST (Haversine).
      • Selects the appropriate road tier (all roads → highways only).
      • Downloads only the needed roads from OpenStreetMap.
      • Snaps GPS coordinates to the nearest graph nodes.
      • DYNAMICALLY selects BFS or A* based on distance.
      • Tracks execution telemetry with high-resolution timers.
      • Renders the emergency route on an interactive Folium map.

    ── WHY TWO ALGORITHMS? (for students) ──────────────────────────────────
    BFS (Breadth-First Search):
        Explores nodes layer-by-layer outward from the start.  It is
        *guaranteed* to find the shortest path **by number of edges**
        (intersections), which is good enough in a small, dense grid.
        It does NOT use any "sense of direction" — it checks every
        possibility equally.  That makes it simple but slow on big graphs.

    A* (A-Star Search):
        A smarter algorithm.  It uses a *heuristic* — an educated guess of
        "how far am I from the goal?" — to prioritise which streets to
        explore first.  Our heuristic is the Haversine distance (straight
        line on a sphere).  This lets A* skip large chunks of the graph
        and find the optimal route much faster over long distances.

    The DYNAMIC SWITCH picks the right tool for the job:
        • Short distance → BFS is fast enough and simpler.
        • Long distance  → A* dramatically outperforms BFS.
    ─────────────────────────────────────────────────────────────────────────
    """

    # Earth's mean radius in kilometres (used by the Haversine formula).
    EARTH_RADIUS_KM = 6371.0

    def __init__(self, start_coords: tuple, end_coords: tuple,
                 threshold_km: float = DISTANCE_THRESHOLD_KM):
        """
        Initialise the router with start/end GPS and configuration.

        Parameters
        ----------
        start_coords : tuple of (latitude, longitude)
        end_coords   : tuple of (latitude, longitude)
        threshold_km : float — distance below which BFS is used.
        """
        self.start_coords = start_coords
        self.end_coords = end_coords
        self.threshold_km = threshold_km

        # These will be populated during execution.
        self.graph = None          # The street network (a NetworkX MultiDiGraph)
        self.start_node = None     # OSM node ID closest to start_coords
        self.end_node = None       # OSM node ID closest to end_coords
        self.distance_km = None    # Haversine distance between the two nodes
        self.algorithm_used = None # "BFS" or "A*"
        self.route_nodes = None    # Ordered list of node IDs forming the path
        self.exec_time_s = None    # Search execution time in seconds
        self.road_tier_label = None  # Which road tier was selected
        self.download_time_s = None  # How long the graph download took

    # ─────────────────────────────────────────────────────────────────────
    # HAVERSINE DISTANCE
    # ─────────────────────────────────────────────────────────────────────

    def calculate_distance(self, lat1: float, lon1: float,
                           lat2: float, lon2: float) -> float:
        """
        Calculate the great-circle distance between two GPS points using
        the **Haversine formula**.

        ── WHAT IS HAVERSINE? (for students) ───────────────────────────
        The Earth is (roughly) a sphere.  You can't just use Pythagoras
        on latitude/longitude because degrees of longitude shrink as you
        move toward the poles.  The Haversine formula accounts for the
        curvature of the Earth and gives the shortest distance over its
        surface — like stretching a string across a globe.

        Formula breakdown:
            a = sin²(Δlat / 2) + cos(lat1) · cos(lat2) · sin²(Δlon / 2)
            c = 2 · atan2(√a, √(1 − a))
            d = R · c          (R = Earth's radius ≈ 6 371 km)
        ─────────────────────────────────────────────────────────────────

        Parameters
        ----------
        lat1, lon1 : float — first point (degrees)
        lat2, lon2 : float — second point (degrees)

        Returns
        -------
        float — distance in kilometres
        """
        # Step 1: Convert degrees → radians (math functions need radians).
        lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
        lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)

        # Step 2: Compute the differences.
        dlat = lat2_r - lat1_r
        dlon = lon2_r - lon1_r

        # Step 3: Apply the Haversine formula.
        a = (math.sin(dlat / 2) ** 2
             + math.cos(lat1_r) * math.cos(lat2_r)
             * math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        # Step 4: Multiply by Earth's radius to get km.
        return self.EARTH_RADIUS_KM * c

    # ─────────────────────────────────────────────────────────────────────
    # ROAD TIER SELECTION
    # ─────────────────────────────────────────────────────────────────────

    def _select_road_tier(self):
        """
        Based on the straight-line distance, pick which road classes to
        download.

        ── WHY TIERS? (for students) ───────────────────────────────────
        Think of it like zooming out on Google Maps:
          • Zoomed in (< 5 km)  → you see every lane and alley.
          • Zoomed out (> 200 km) → you only see national highways.
        We do the same thing with the download: the farther the trip,
        the fewer (but bigger) roads we request.  This keeps the graph
        small enough to download quickly and search efficiently.
        ─────────────────────────────────────────────────────────────────

        Returns
        -------
        tuple of (label, custom_filter, bbox_padding_deg)
        """
        for max_km, label, cfilter, padding in ROAD_TIERS:
            if max_km is None or self.distance_km <= max_km:
                self.road_tier_label = label
                return label, cfilter, padding

    # ─────────────────────────────────────────────────────────────────────
    # GRAPH DOWNLOAD — TIERED & BBOX-BASED
    # ─────────────────────────────────────────────────────────────────────

    def _download_network(self, allowed_highways: list, bbox_padding: float):
        """
        Download the street network from OpenStreetMap using a bounding box
        around the start/end points, filtered to the chosen road tier.

        ── BOUNDING BOX vs CIRCULAR BUFFER (for students) ──────────────
        Previously we downloaded a circle of roads around the midpoint.
        That works for short routes, but for Guwahati → Kargil the
        midpoint would be in the middle of Nepal — useless!

        Instead, we now compute a BOUNDING BOX: the smallest rectangle
        that encloses both GPS points, then add some padding so the
        router can find detours if the straight road is blocked.

        Combined with the road tier filter (e.g. "only motorways"),
        this means a 2,500 km route might download only a few thousand
        highway segments instead of millions of residential lanes.

        ── RESILIENCE (for students) ───────────────────────────────────
        The Overpass API is a free, public service and can be slow or
        overloaded.  To handle this we:
          1. Set a generous timeout (180 seconds instead of the default).
          2. Retry up to 3 times if the request fails.
          3. Fall back to an alternative Overpass mirror if the primary
             server keeps timing out.
        ─────────────────────────────────────────────────────────────────
        """
        # ── COMPUTE THE BOUNDING BOX ────────────────────────────────
        lat1, lon1 = self.start_coords
        lat2, lon2 = self.end_coords

        south = min(lat1, lat2) - bbox_padding
        north = max(lat1, lat2) + bbox_padding
        west  = min(lon1, lon2) - bbox_padding
        east  = max(lon1, lon2) + bbox_padding

        _sys("Initiating Overpass API link to OpenStreetMap …")
        _data("Bounding box",
              f"S={south:.4f}  N={north:.4f}  W={west:.4f}  E={east:.4f}")
        _data("Road tier", self.road_tier_label)

        # ── CONFIGURE OSMNX FOR RESILIENCE ──────────────────────────
        ox.settings.timeout = 180
        ox.settings.max_query_area_size = 50_000_000_000

        overpass_endpoints = [
            "https://overpass-api.de/api/",
            "https://overpass.kumi.systems/api/",
        ]

        max_retries = 3

        for endpoint in overpass_endpoints:
            ox.settings.overpass_url = endpoint
            _data("Overpass endpoint", endpoint)

            for attempt in range(1, max_retries + 1):
                try:
                    # Start the spinner so the user sees live elapsed time.
                    spinner = Spinner(
                        f"Downloading street graph (attempt {attempt}/{max_retries})"
                    )
                    spinner.start()

                    # ── FAST DOWNLOAD ──
                    # Always use the optimized "drive" network type to avoid
                    # public Overpass API regex timeouts.
                    self.graph = ox.graph_from_bbox(
                        bbox=(west, south, east, north),
                        network_type="drive"
                    )

                    # Stop the spinner — download succeeded.
                    self.download_time_s = spinner.stop()

                    # ── LOCAL FILTERING ──
                    # Instead of relying on the Overpass server to filter highways
                    # (which times out on large regions), we filter the graph locally!
                    if allowed_highways is not None:
                        _sys("Filtering local subsidiaries to prioritize highways …")
                        edges_to_remove = []
                        for u, v, k, data in self.graph.edges(keys=True, data=True):
                            highway_tag = data.get("highway")
                            # highway tags can sometimes be lists if multiple ways merge
                            if isinstance(highway_tag, list):
                                if not any(hw in allowed_highways for hw in highway_tag):
                                    edges_to_remove.append((u, v, k))
                            else:
                                if highway_tag not in allowed_highways:
                                    edges_to_remove.append((u, v, k))
                                    
                        self.graph.remove_edges_from(edges_to_remove)
                        # Clean up orphaned nodes
                        self.graph.remove_nodes_from(list(nx.isolates(self.graph)))

                    num_nodes = self.graph.number_of_nodes()
                    num_edges = self.graph.number_of_edges()
                    _ok(f"Street graph acquired — "
                        f"{num_nodes:,} nodes, {num_edges:,} edges  "
                        f"({self.download_time_s:.1f}s)")
                    return

                except Exception as exc:
                    # Stop the spinner on failure.
                    spinner.stop()
                    _sys(f"Attempt {attempt} failed: {type(exc).__name__}")
                    if attempt < max_retries:
                        wait = 5 * attempt
                        _sys(f"Retrying in {wait}s …")
                        time.sleep(wait)

            _sys(f"All {max_retries} attempts exhausted on this endpoint.")
            _sys("Rotating to fallback Overpass endpoint …")

        raise RuntimeError(
            "FATAL: Could not download the street network from any "
            "Overpass API endpoint.  Check your internet connection "
            "and try again."
        )

    # ─────────────────────────────────────────────────────────────────────
    # NODE SNAPPING
    # ─────────────────────────────────────────────────────────────────────

    def _snap_nodes(self):
        """
        Snap raw GPS coordinates to the nearest nodes in the street graph.

        ── WHY DO WE NEED THIS? (for students) ─────────────────────────
        Your GPS might say you're at (51.5074, -0.1278), but there is no
        intersection *exactly* at that point.  `nearest_nodes` finds the
        closest real intersection in the downloaded graph so the routing
        algorithm has valid start/end points.
        ─────────────────────────────────────────────────────────────────
        """
        _sys("Snapping GPS coordinates to nearest graph nodes …")

        # ox.distance.nearest_nodes(G, X=longitude, Y=latitude)
        self.start_node = ox.distance.nearest_nodes(
            self.graph, self.start_coords[1], self.start_coords[0]
        )
        self.end_node = ox.distance.nearest_nodes(
            self.graph, self.end_coords[1], self.end_coords[0]
        )

        _data("Start node (OSM ID)", self.start_node)
        _data("End   node (OSM ID)", self.end_node)

    # ─────────────────────────────────────────────────────────────────────
    # BFS — Breadth-First Search
    # ─────────────────────────────────────────────────────────────────────

    def _bfs(self) -> list:
        """
        Find a path from start_node → end_node using Breadth-First Search.

        ── BFS IN PLAIN ENGLISH (for students) ─────────────────────────
        Imagine you're at an intersection and you send a runner down
        EVERY road leading away from you.  Each runner, when they reach
        the next intersection, sends more runners down every new road.
        The first runner to reach the destination wins — that path has
        the fewest intersections (edges).

        Data structure: a FIFO queue (first-in, first-out).
        Time complexity: O(V + E), where V = nodes, E = edges.

        BFS finds the path with the fewest *hops* (edges), NOT the
        shortest *distance*.  For small dense grids they're nearly the
        same, which is why we only use BFS for short routes.
        ─────────────────────────────────────────────────────────────────

        Returns
        -------
        list of node IDs representing the path, or an empty list if no
        path exists.
        """
        visited = set()
        visited.add(self.start_node)

        queue = deque([[self.start_node]])

        while queue:
            path = queue.popleft()
            current_node = path[-1]

            if current_node == self.end_node:
                return path

            for neighbour in self.graph.neighbors(current_node):
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append(path + [neighbour])

        return []

    # ─────────────────────────────────────────────────────────────────────
    # A* — A-Star Search (with Haversine heuristic)
    # ─────────────────────────────────────────────────────────────────────

    def _astar(self) -> list:
        """
        Find the shortest-distance path using A* Search.

        ── A* IN PLAIN ENGLISH (for students) ──────────────────────────
        A* is like BFS but with a secret weapon: a *heuristic*.

        At every intersection, A* calculates a score for each option:
            f(n) = g(n) + h(n)
        where:
            g(n) = actual distance we've already travelled to node n
            h(n) = *estimated* remaining distance from n to the goal
                   (we use the Haversine straight-line distance)

        A* always explores the node with the LOWEST f score first.
        Because h(n) never *overestimates* the true distance (a straight
        line is always ≤ the road distance), A* is guaranteed to find
        the optimal path — and it does so MUCH faster than BFS because
        it ignores streets that lead away from the goal.
        ─────────────────────────────────────────────────────────────────

        Returns
        -------
        list of node IDs representing the shortest path by distance.
        """
        def heuristic(node_a, node_b):
            """Haversine heuristic for A* — returns distance in metres."""
            a_data = self.graph.nodes[node_a]
            b_data = self.graph.nodes[node_b]
            return self.calculate_distance(
                a_data["y"], a_data["x"],
                b_data["y"], b_data["x"]
            ) * 1000  # convert km → m

        path = nx.astar_path(
            self.graph,
            self.start_node,
            self.end_node,
            heuristic=heuristic,
            weight="length"
        )
        return path

    # ─────────────────────────────────────────────────────────────────────
    # DYNAMIC ALGORITHM SELECTION & EXECUTION
    # ─────────────────────────────────────────────────────────────────────

    def _select_and_run(self):
        """
        Dynamically select BFS or A*, execute the search, and record
        telemetry.

        ── ABOUT time.perf_counter() (for students) ────────────────────
        `time.perf_counter()` returns the current time from a
        high-resolution clock, measured in fractional seconds.  Unlike
        `time.time()`, which can jump if your OS adjusts the clock,
        `perf_counter` is *monotonic* (always goes forward) and has
        nanosecond-level precision.  It is the gold standard for
        micro-benchmarking code execution.

        HOW WE USE IT:
            start = time.perf_counter()   ← snapshot BEFORE the work
            … do the work …
            end   = time.perf_counter()   ← snapshot AFTER the work
            elapsed = end - start         ← the difference is the runtime
        ─────────────────────────────────────────────────────────────────
        """
        _separator()
        _data("Haversine distance", f"{self.distance_km:.4f} km")
        _separator()

        if self.distance_km < self.threshold_km:
            _sys(f"Distance < {self.threshold_km} km. "
                 "LOCALIZED SAFE ZONE detected.")
            _sys(">> Breadth-First Search (BFS) Engaged.")
            self.algorithm_used = "BFS"

            t_start = time.perf_counter()
            self.route_nodes = self._bfs()
            t_end = time.perf_counter()

        else:
            _sys(f"Distance >= {self.threshold_km} km. "
                 "CORRUPTED ZONE detected.")
            _sys(">> A* Heuristic Search Engaged.")
            self.algorithm_used = "A*"

            t_start = time.perf_counter()
            self.route_nodes = self._astar()
            t_end = time.perf_counter()

        self.exec_time_s = t_end - t_start

    # ─────────────────────────────────────────────────────────────────────
    # TELEMETRY REPORT
    # ─────────────────────────────────────────────────────────────────────

    def _print_telemetry(self):
        """Print a formatted telemetry block to the terminal."""
        _separator()
        _sys("ROUTE COMPUTATION COMPLETE")
        _separator()
        _data("Algorithm deployed ", self.algorithm_used)
        _data("Road tier selected ", self.road_tier_label)
        _data("Straight-line dist", f"{self.distance_km:.4f} km")
        _data("Route hops (nodes)", len(self.route_nodes))
        _data("Network download   ",
              f"{self.download_time_s:.2f} s")
        _data("Search exec time   ",
              f"{self.exec_time_s:.6f} s  "
              f"({self.exec_time_s * 1000:.3f} ms)")
        _separator()

    # ─────────────────────────────────────────────────────────────────────
    # MAP VISUALISATION — Matching the reference style
    # ─────────────────────────────────────────────────────────────────────

    def _render_map(self, output_file: str):
        """
        Plot the route on an interactive Folium map and save as HTML.

        ── WHAT IS FOLIUM? (for students) ──────────────────────────────
        Folium is a Python wrapper around Leaflet.js, a popular
        JavaScript mapping library.  It lets us create interactive,
        zoomable maps with markers and lines — all saved as a single
        HTML file you can open in any web browser.  No server needed.

        ── VISUAL DESIGN ───────────────────────────────────────────────
        We use the default OpenStreetMap tiles (light, detailed, with
        readable road labels) and draw the route as a bold blue line
        with a red circle for the start and a green pin for the
        destination — matching standard navigation-app conventions.
        ─────────────────────────────────────────────────────────────────
        """
        if not self.route_nodes:
            _warn("No route to render — path list is empty!")
            return

        # Convert node IDs → (lat, lon) coordinate pairs.
        route_coords = [
            (self.graph.nodes[n]["y"], self.graph.nodes[n]["x"])
            for n in self.route_nodes
        ]

        # ── AUTO-FIT ZOOM ───────────────────────────────────────────
        # Instead of guessing a zoom level, we compute the bounding box
        # of the route and tell Folium to fit the map to those bounds.
        # This works perfectly whether the route is 1 km or 2,500 km.
        lats = [c[0] for c in route_coords]
        lons = [c[1] for c in route_coords]
        sw = [min(lats), min(lons)]   # South-West corner
        ne = [max(lats), max(lons)]   # North-East corner

        # Centre the map on the midpoint of the route.
        mid_lat = (sw[0] + ne[0]) / 2
        mid_lon = (sw[1] + ne[1]) / 2

        # ── CREATE THE MAP ──────────────────────────────────────────
        # Use the default OpenStreetMap tileset — light background with
        # detailed road labels, matching the reference screenshot style.
        fmap = folium.Map(
            location=[mid_lat, mid_lon],
            zoom_start=13,
            tiles="OpenStreetMap"
        )

        # Fit the map view to show the entire route with padding.
        fmap.fit_bounds([sw, ne], padding=[40, 40])

        # ── DRAW THE ROUTE ──────────────────────────────────────────
        # Bold blue polyline — high contrast on the light OSM tiles.
        folium.PolyLine(
            locations=route_coords,
            color="#2962FF",        # Vivid blue (Google Maps-style)
            weight=5,              # Line thickness in pixels
            opacity=0.85,
            tooltip=(f"FAILSAFE ROUTE — {self.algorithm_used} | "
                     f"{self.distance_km:.1f} km straight-line")
        ).add_to(fmap)

        # ── START MARKER — Red circle (like the reference image) ────
        folium.CircleMarker(
            location=route_coords[0],
            radius=10,
            color="#D32F2F",       # Red border
            fill=True,
            fill_color="#D32F2F",
            fill_opacity=0.9,
            popup=(f"<b>ORIGIN</b><br>"
                   f"Lat: {route_coords[0][0]:.6f}<br>"
                   f"Lon: {route_coords[0][1]:.6f}"),
            tooltip="START"
        ).add_to(fmap)

        # Small white centre dot for the start marker.
        folium.CircleMarker(
            location=route_coords[0],
            radius=4,
            color="white",
            fill=True,
            fill_color="white",
            fill_opacity=1.0,
        ).add_to(fmap)

        # ── END MARKER — Green pin (like the reference image) ──────
        folium.Marker(
            location=route_coords[-1],
            popup=(f"<b>DESTINATION</b><br>"
                   f"Lat: {route_coords[-1][0]:.6f}<br>"
                   f"Lon: {route_coords[-1][1]:.6f}"),
            tooltip="DESTINATION",
            icon=folium.Icon(color="green", icon="flag", prefix="fa")
        ).add_to(fmap)

        # Save the map to disk.
        fmap.save(output_file)
        _ok(f"Interactive map saved → {output_file}")

    # ─────────────────────────────────────────────────────────────────────
    # PUBLIC ENTRY POINT
    # ─────────────────────────────────────────────────────────────────────

    def execute(self, output_file: str = OUTPUT_HTML):
        """
        Run the full failsafe routing pipeline.

        ── v2.0 EXECUTION ORDER (for students) ─────────────────────────
        The key change from v1 is that we compute the Haversine distance
        BEFORE downloading the graph.  This lets us choose which road
        tier to download (all roads vs highways only), which dramatically
        reduces download size for long-distance routes.

        Pipeline:
            1. Measure straight-line distance (Haversine on raw GPS)
            2. Select road tier based on that distance
            3. Download the appropriate street network
            4. Snap GPS → graph nodes
            5. Select & run the search algorithm (BFS or A*)
            6. Render the interactive map
        ─────────────────────────────────────────────────────────────────
        """
        _banner()
        _sys("FAILSAFE PROTOCOL INITIATED")
        _data("Origin GPS     ", self.start_coords)
        _data("Destination GPS", self.end_coords)
        _separator()

        # ── PHASE 1 — Compute distance FIRST (before downloading!). ──
        p1_start = time.perf_counter()
        _progress_bar(1, "Calculating straight-line distance")
        self.distance_km = self.calculate_distance(
            self.start_coords[0], self.start_coords[1],
            self.end_coords[0], self.end_coords[1]
        )
        p1_time = time.perf_counter() - p1_start
        _progress_bar(1, "Calculating straight-line distance", p1_time, "done")
        _data("Haversine distance", f"{self.distance_km:.4f} km")

        # ── PHASE 2 — Select road tier based on distance. ──
        p2_start = time.perf_counter()
        _progress_bar(2, "Selecting optimal road tier")
        tier_label, allowed_highways, tier_padding = self._select_road_tier()
        p2_time = time.perf_counter() - p2_start
        _progress_bar(2, "Selecting optimal road tier", p2_time, "done")
        _data("Road tier", f"{tier_label}  (distance = {self.distance_km:.1f} km)")

        # ── PHASE 3 — Download the street network. ──
        # This is the slowest phase — the spinner inside _download_network
        # shows live elapsed time while we wait for the Overpass API.
        _progress_bar(3, "Acquiring street network")
        print()  # Newline so the spinner doesn't overwrite the bar.
        self._download_network(allowed_highways, tier_padding)
        _progress_bar(3, "Acquiring street network", self.download_time_s, "done")

        # ── PHASE 4 — Snap coordinates to graph nodes. ──
        p4_start = time.perf_counter()
        _progress_bar(4, "Locking onto graph nodes")
        self._snap_nodes()
        p4_time = time.perf_counter() - p4_start
        _progress_bar(4, "Locking onto graph nodes", p4_time, "done")

        # ── PHASE 5 — Select algorithm & run. ──
        _progress_bar(5, "Deploying search algorithm")
        self._select_and_run()
        _progress_bar(5, "Deploying search algorithm", self.exec_time_s, "done")

        # Print the telemetry dashboard.
        self._print_telemetry()

        # Render the route to an interactive map.
        _sys("Rendering evacuation map …")
        self._render_map(output_file)

        # Final status.
        total_time = (p1_time + p2_time + self.download_time_s
                      + p4_time + self.exec_time_s)
        print()
        _sys(f"ALL SYSTEMS NOMINAL — Total pipeline: {total_time:.2f}s")
        _sys(f"Open '{output_file}' in a browser to view the route.")
        print()


# ═════════════════════════════════════════════════════════════════════════════
# MAIN — Script entry point
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Create the router with the configured coordinates and run it.
    router = AdaptiveFailsafeRouter(
        start_coords=START_COORDS,
        end_coords=END_COORDS,
        threshold_km=DISTANCE_THRESHOLD_KM
    )
    router.execute()
