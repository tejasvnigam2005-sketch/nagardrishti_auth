import copy
import json
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

import httpx

from ..config import SHARED_DB_PATH, LOCAL_BACKUP_DB_PATH, USER_SITE_API_URL
from ..models.schemas import (
    Complaint,
    ComplaintCreate,
    ComplaintStatus,
    DashboardStatistics,
    Department,
    HeatmapPoint,
    HotspotInfo,
    DailyTrendPoint,
)

logger = logging.getLogger(__name__)

# Municipal Departments matching the civic taxonomy
INITIAL_DEPARTMENTS: List[Department] = [
    Department(id="dept-1", name="Municipal Roads (PWD)", category="Roads & Bridges", is_active=True),
    Department(id="dept-2", name="MCD Sanitation & Solid Waste", category="Sanitation", is_active=True),
    Department(id="dept-3", name="BSES / Municipal Street Lighting Cell", category="Street Lighting", is_active=True),
    Department(id="dept-4", name="Delhi Jal Board (DJB)", category="Drainage & Water", is_active=True),
    Department(id="dept-5", name="Delhi Traffic Police & Civic Oversight", category="Traffic & Hazards", is_active=True),
]


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two GPS coordinates in meters."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def calculate_hotspots(complaints: List[Complaint]) -> List[HotspotInfo]:
    """
    Deterministic spatial clustering algorithm matching NagarDrishti-AI.
    Groups complaint coordinates into geographic clusters (~1.4km corridor radius).
    Computes centroids, repeated counts, unresolved ratios, dominant categories,
    and municipal suggested actions.
    """
    if not complaints:
        return []

    clusters: List[Dict[str, Any]] = []
    MAX_CLUSTER_DIST_METERS = 1400.0

    for c in complaints:
        lat = c.latitude
        lng = c.longitude
        if lat is None or lng is None:
            continue

        matched_cluster = None
        for cl in clusters:
            dist = haversine_distance_meters(lat, lng, cl["centroid_lat"], cl["centroid_lng"])
            if dist <= MAX_CLUSTER_DIST_METERS:
                matched_cluster = cl
                break

        if matched_cluster:
            matched_cluster["reports"].append(c)
            reps = matched_cluster["reports"]
            matched_cluster["centroid_lat"] = sum(r.latitude for r in reps) / len(reps)
            matched_cluster["centroid_lng"] = sum(r.longitude for r in reps) / len(reps)
            d = haversine_distance_meters(lat, lng, matched_cluster["centroid_lat"], matched_cluster["centroid_lng"])
            if d > matched_cluster.get("max_dist_m", 400.0):
                matched_cluster["max_dist_m"] = d
        else:
            clusters.append({
                "centroid_lat": lat,
                "centroid_lng": lng,
                "max_dist_m": 400.0,
                "reports": [c]
            })

    hotspot_list: List[HotspotInfo] = []
    now_utc = datetime.now(timezone.utc)
    three_days_ago = (now_utc - timedelta(days=3)).isoformat()

    title_map = {
        "pothole": "ROAD SAFETY HOTSPOT",
        "garbage": "SOLID WASTE ACCUMULATION HOTSPOT",
        "streetlight": "LIGHTING & ELECTRICAL HAZARD HOTSPOT",
        "drain": "DRAINAGE & STORM OVERFLOW HOTSPOT",
        "other": "CIVIC INFRASTRUCTURE HOTSPOT"
    }
    action_map = {
        "pothole": "Deploy emergency night milling and asphalt patching squad",
        "garbage": "Double municipal secondary compactor frequency and clear blockage",
        "streetlight": "Dispatch electrical inspection crew and secure overhead wiring",
        "drain": "Desilt arterial stormwater trunk lines and clear inlet grating",
        "other": "Conduct joint on-site inspection with local zonal officer"
    }

    for idx, cl in enumerate(clusters):
        reps: List[Complaint] = cl["reports"]
        total_reps = len(reps)
        cat_counts: Dict[str, int] = {}
        for r in reps:
            cat = r.problem_type
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        dominant_cat = max(cat_counts, key=cat_counts.get) if cat_counts else "other"
        repeated_count = cat_counts.get(dominant_cat, 0)
        unresolved = sum(1 for r in reps if r.status != "RESOLVED")
        high_critical = sum(1 for r in reps if r.severity in ["HIGH", "CRITICAL"])

        title = title_map.get(dominant_cat, "MUNICIPAL CIVIC HOTSPOT")
        action = action_map.get(dominant_cat, "Inspect affected municipal corridor")
        radius_km = round(max(0.4, cl["max_dist_m"] / 1000.0), 1)

        recent_count = sum(1 for r in reps if r.created_at >= three_days_ago)
        trend_pct = int((recent_count / total_reps) * 45) if total_reps > 0 else 10

        hotspot_list.append(HotspotInfo(
            id=f"hs-{idx + 1}",
            title=title,
            dominant_issue=f"{dominant_cat.capitalize()} ({repeated_count} reports in corridor)",
            total_reports=total_reps,
            unresolved_count=unresolved,
            high_critical_count=high_critical,
            trend_percentage=float(max(12, trend_pct)),
            suggested_action=action,
            latitude=round(cl["centroid_lat"], 5),
            longitude=round(cl["centroid_lng"], 5),
            radius_km=radius_km,
            repeated_count=repeated_count,
            report_ids=[r.report_id for r in reps]
        ))

    hotspot_list.sort(key=lambda h: h.total_reports, reverse=True)
    return hotspot_list


def calculate_daily_trends(complaints: List[Complaint]) -> List[DailyTrendPoint]:
    """
    Computes actual 7-day complaint intake volume from database records.
    Returns ordered list of daily trend points (Mon-Sun).
    """
    now_utc = datetime.now(timezone.utc)
    day_counts: Dict[str, int] = {}
    day_labels: Dict[str, str] = {}

    for i in range(6, -1, -1):
        dt = now_utc - timedelta(days=i)
        key = dt.strftime("%Y-%m-%d")
        day_counts[key] = 0
        day_labels[key] = dt.strftime("%a")

    for c in complaints:
        if c.created_at:
            try:
                dt = datetime.fromisoformat(c.created_at.replace("Z", "+00:00"))
                key = dt.strftime("%Y-%m-%d")
                if key in day_counts:
                    day_counts[key] += 1
            except Exception:
                pass

    trends = []
    for key in sorted(day_counts.keys()):
        trends.append(DailyTrendPoint(
            date=key,
            day_label=day_labels.get(key, key),
            count=day_counts[key]
        ))
    return trends


class CivicDataStore:
    """
    Connected data store bridging the Authority Portal directly to the NagarDrishti-AI citizen platform.
    Features:
    - Shared disk persistence to complaints_db.json
    - Dynamic mtime cache auto-reload so citizen reports appear in real-time
    - Dynamic spatial clustering for Hotspot Intelligence
    - Dynamic 7-day daily intake volume trends
    - Live synchronization with NagarDrishti-AI backend API (if running)
    - Full lifecycle management (REPORTED -> ASSIGNED -> IN_PROGRESS -> RESOLVED)
    """

    def __init__(self):
        self.departments: List[Department] = copy.deepcopy(INITIAL_DEPARTMENTS)
        self.complaints: List[Complaint] = []
        self._last_mtime: float = 0.0
        self._report_seq = 119
        self._load_from_storage()

    def _get_storage_targets(self) -> List[Path]:
        targets = []
        for p_str in [SHARED_DB_PATH, LOCAL_BACKUP_DB_PATH]:
            if p_str:
                p = Path(p_str)
                try:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    targets.append(p)
                except Exception as e:
                    logger.warning(f"Could not prepare path {p_str}: {e}")
        return targets

    def _load_from_storage(self):
        """Loads complaints from the shared database file."""
        targets = self._get_storage_targets()
        loaded = False

        for target in targets:
            if target.exists() and target.stat().st_size > 5:
                try:
                    with open(target, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        parsed = []
                        max_seq = 118
                        for item in data:
                            try:
                                c = Complaint(**item)
                                parsed.append(c)
                                rep = str(c.report_id)
                                if rep.startswith("NGD-2026-"):
                                    try:
                                        s = int(rep.split("-")[-1])
                                        if s > max_seq:
                                            max_seq = s
                                    except ValueError:
                                        pass
                            except Exception as parse_err:
                                logger.warning(f"Error parsing complaint record: {parse_err}")
                        if parsed:
                            self.complaints = parsed
                            self._report_seq = max_seq + 1
                            self._last_mtime = target.stat().st_mtime
                            logger.info(f"Loaded {len(parsed)} complaints from {target}")
                            loaded = True
                            break
                except Exception as e:
                    logger.warning(f"Failed to load from {target}: {e}")

        if not loaded:
            # If storage doesn't exist yet, seed with authentic Delhi complaints from NagarDrishti-AI
            self._seed_initial_records()
            self._save_to_storage()

    def _seed_initial_records(self):
        """Seeds the 16 authentic Delhi civic complaints matching NagarDrishti-AI."""
        now_utc = datetime.now(timezone.utc)

        def dt_off(d: int, h: int = 0) -> str:
            return (now_utc - timedelta(days=d, hours=h)).isoformat()

        seed_data = [
            Complaint(
                id="c001",
                report_id="NGD-2026-00101",
                problem_type="pothole",
                confidence=0.94,
                severity="HIGH",
                evidence=["Large cavity visible in active road lane", "Cracked asphalt with water pooling"],
                latitude=28.6315,
                longitude=77.2167,
                location_name="Connaught Place Outer Circle near Radial 2",
                department="Municipal Roads (PWD)",
                description="Hazardous pothole causing two-wheeler skids near metro gate.",
                image_url="https://images.unsplash.com/photo-1515162816999-a0c47dc192f7?w=800&auto=format&fit=crop&q=60",
                status="REPORTED",
                duplicate_of=None,
                created_at=dt_off(3, 4),
                updated_at=dt_off(3, 4),
            ),
            Complaint(
                id="c005",
                report_id="NGD-2026-00105",
                problem_type="pothole",
                confidence=0.82,
                severity="MEDIUM",
                evidence=["Asphalt wear and shallow road rutting"],
                latitude=28.6322,
                longitude=77.2175,
                location_name="Near Shivaji Stadium Terminal",
                department="Municipal Roads (PWD)",
                description="Road surface cracking and minor pothole developing.",
                image_url="https://images.unsplash.com/photo-1515162816999-a0c47dc192f7?w=800&auto=format&fit=crop&q=60",
                status="RESOLVED",
                duplicate_of=None,
                created_at=dt_off(5, 6),
                updated_at=dt_off(1, 2),
            ),
            Complaint(
                id="c008",
                report_id="NGD-2026-00108",
                problem_type="pothole",
                confidence=0.91,
                severity="CRITICAL",
                evidence=["Deep road collapse cave-in exposing base gravel", "Severe vehicular obstruction"],
                latitude=28.6310,
                longitude=77.2160,
                location_name="Radial Road 3, Connaught Place",
                department="Municipal Roads (PWD)",
                description="Cave-in on inner lane, traffic backed up.",
                image_url="https://images.unsplash.com/photo-1515162816999-a0c47dc192f7?w=800&auto=format&fit=crop&q=60",
                status="IN_PROGRESS",
                duplicate_of=None,
                created_at=dt_off(1, 8),
                updated_at=dt_off(0, 4),
            ),
            Complaint(
                id="c009",
                report_id="NGD-2026-00109",
                problem_type="pothole",
                confidence=0.93,
                severity="HIGH",
                evidence=["Cavity in road lane matching recent report"],
                latitude=28.6316,
                longitude=77.2168,
                location_name="Connaught Place Outer Circle, Metro Gate 4",
                department="Municipal Roads (PWD)",
                description="Duplicate report submitted by nearby pedestrian.",
                image_url="https://images.unsplash.com/photo-1515162816999-a0c47dc192f7?w=800&auto=format&fit=crop&q=60",
                status="REPORTED",
                duplicate_of="NGD-2026-00101",
                created_at=dt_off(0, 3),
                updated_at=dt_off(0, 3),
            ),
            Complaint(
                id="c002",
                report_id="NGD-2026-00102",
                problem_type="garbage",
                confidence=0.91,
                severity="CRITICAL",
                evidence=["Solid waste accumulation blocking entire pedestrian pavement", "Overflowing open municipal bin"],
                latitude=28.6520,
                longitude=77.1905,
                location_name="Ajmal Khan Road Market, Karol Bagh",
                department="MCD Sanitation & Solid Waste",
                description="Severe stench and pedestrian pathway completely obstructed.",
                image_url="https://images.unsplash.com/photo-1605600659908-0ef719419d41?w=800&auto=format&fit=crop&q=60",
                status="ASSIGNED",
                duplicate_of=None,
                created_at=dt_off(4, 2),
                updated_at=dt_off(2, 1),
            ),
            Complaint(
                id="c010",
                report_id="NGD-2026-00110",
                problem_type="garbage",
                confidence=0.89,
                severity="HIGH",
                evidence=["Debris pile spilling onto main commercial road", "Scattered organic waste"],
                latitude=28.6532,
                longitude=77.1912,
                location_name="Arya Samaj Road crossing, Karol Bagh",
                department="MCD Sanitation & Solid Waste",
                description="Commercial waste dumped overnight near vegetable market.",
                image_url="https://images.unsplash.com/photo-1605600659908-0ef719419d41?w=800&auto=format&fit=crop&q=60",
                status="REPORTED",
                duplicate_of=None,
                created_at=dt_off(2, 5),
                updated_at=dt_off(2, 5),
            ),
            Complaint(
                id="c011",
                report_id="NGD-2026-00111",
                problem_type="garbage",
                confidence=0.85,
                severity="MEDIUM",
                evidence=["Accumulated packaging waste outside electronics shops"],
                latitude=28.6515,
                longitude=77.1895,
                location_name="Gaffar Market Entry Gate, Karol Bagh",
                department="MCD Sanitation & Solid Waste",
                description="Cardboard and plastic bags piling up.",
                image_url="https://images.unsplash.com/photo-1605600659908-0ef719419d41?w=800&auto=format&fit=crop&q=60",
                status="IN_PROGRESS",
                duplicate_of=None,
                created_at=dt_off(3, 7),
                updated_at=dt_off(0, 5),
            ),
            Complaint(
                id="c003",
                report_id="NGD-2026-00103",
                problem_type="streetlight",
                confidence=0.88,
                severity="MEDIUM",
                evidence=["Damaged light fixture head hanging unlit", "Pole bent slightly at base"],
                latitude=28.6280,
                longitude=77.2060,
                location_name="Gole Market Road, Sector 4",
                department="BSES / Municipal Street Lighting Cell",
                description="Dark spot on road during night, posing safety hazard for pedestrians.",
                image_url="https://images.unsplash.com/photo-1517457373958-b7bdd4587205?w=800&auto=format&fit=crop&q=60",
                status="IN_PROGRESS",
                duplicate_of=None,
                created_at=dt_off(4, 9),
                updated_at=dt_off(1, 4),
            ),
            Complaint(
                id="c012",
                report_id="NGD-2026-00112",
                problem_type="streetlight",
                confidence=0.92,
                severity="HIGH",
                evidence=["Streetlight lamp shattered with loose dangling wires"],
                latitude=28.6292,
                longitude=77.2050,
                location_name="Bhai Veer Singh Marg, Gole Market",
                department="BSES / Municipal Street Lighting Cell",
                description="Three consecutive light poles dark at school crossing.",
                image_url="https://images.unsplash.com/photo-1517457373958-b7bdd4587205?w=800&auto=format&fit=crop&q=60",
                status="REPORTED",
                duplicate_of=None,
                created_at=dt_off(1, 3),
                updated_at=dt_off(1, 3),
            ),
            Complaint(
                id="c013",
                report_id="NGD-2026-00113",
                problem_type="streetlight",
                confidence=0.95,
                severity="CRITICAL",
                evidence=["Pole bent at 45 degree angle across sidewalk", "Live electrical wiring visible"],
                latitude=28.6275,
                longitude=77.2070,
                location_name="Peshwa Road Junction, Gole Market",
                department="BSES / Municipal Street Lighting Cell",
                description="Accident vehicle struck pole, sparks reported during rainfall.",
                image_url="https://images.unsplash.com/photo-1517457373958-b7bdd4587205?w=800&auto=format&fit=crop&q=60",
                status="ASSIGNED",
                duplicate_of=None,
                created_at=dt_off(0, 6),
                updated_at=dt_off(0, 2),
            ),
            Complaint(
                id="c004",
                report_id="NGD-2026-00104",
                problem_type="drain",
                confidence=0.95,
                severity="HIGH",
                evidence=["Open stormwater gutter overflowing onto road surface", "Debris clogging inlet grate"],
                latitude=28.6185,
                longitude=77.2210,
                location_name="Janpath Lane near Central Cottage",
                department="Delhi Jal Board (DJB)",
                description="Foul drain water spilling over the asphalt.",
                image_url="https://images.unsplash.com/photo-1541888946425-d0fbb18086f6?w=800&auto=format&fit=crop&q=60",
                status="REPORTED",
                duplicate_of=None,
                created_at=dt_off(2, 8),
                updated_at=dt_off(2, 8),
            ),
            Complaint(
                id="c014",
                report_id="NGD-2026-00114",
                problem_type="drain",
                confidence=0.93,
                severity="CRITICAL",
                evidence=["Complete drain canal overflow flooding bus stop", "Black sewage water backup"],
                latitude=28.6195,
                longitude=77.2225,
                location_name="Tolstoy Marg Bus Shelter, Janpath",
                department="Delhi Jal Board (DJB)",
                description="Pedestrians unable to access bus stop due to sewage flood.",
                image_url="https://images.unsplash.com/photo-1541888946425-d0fbb18086f6?w=800&auto=format&fit=crop&q=60",
                status="IN_PROGRESS",
                duplicate_of=None,
                created_at=dt_off(1, 10),
                updated_at=dt_off(0, 6),
            ),
            Complaint(
                id="c015",
                report_id="NGD-2026-00115",
                problem_type="drain",
                confidence=0.81,
                severity="LOW",
                evidence=["Minor curb runoff pooling near storm grate"],
                latitude=28.6178,
                longitude=77.2198,
                location_name="Windsor Place Roundabout, Janpath",
                department="Delhi Jal Board (DJB)",
                description="Drain grate cleaned and water receding.",
                image_url="https://images.unsplash.com/photo-1541888946425-d0fbb18086f6?w=800&auto=format&fit=crop&q=60",
                status="RESOLVED",
                duplicate_of=None,
                created_at=dt_off(6, 4),
                updated_at=dt_off(2, 2),
            ),
            Complaint(
                id="c016",
                report_id="NGD-2026-00116",
                problem_type="other",
                confidence=0.76,
                severity="LOW",
                evidence=["Damaged metal divider barricade on sidewalk boundary"],
                latitude=28.6250,
                longitude=77.2120,
                location_name="Sansad Marg near Patel Chowk",
                department="Delhi Traffic Police & Civic Oversight",
                description="Barricade leaning into footpath.",
                image_url="https://images.unsplash.com/photo-1541888946425-d0fbb18086f6?w=800&auto=format&fit=crop&q=60",
                status="REPORTED",
                duplicate_of=None,
                created_at=dt_off(0, 1),
                updated_at=dt_off(0, 1),
            ),
            Complaint(
                id="c017",
                report_id="NGD-2026-00117",
                problem_type="pothole",
                confidence=0.85,
                severity="LOW",
                evidence=["Minor road surface crack repaved"],
                latitude=28.6310,
                longitude=77.2162,
                location_name="Connaught Place Inner Circle Radial 1",
                department="Municipal Roads (PWD)",
                description="Crack in road sealed by maintenance team.",
                image_url="https://images.unsplash.com/photo-1515162816999-a0c47dc192f7?w=800&auto=format&fit=crop&q=60",
                status="RESOLVED",
                duplicate_of=None,
                created_at=dt_off(5, 2),
                updated_at=dt_off(1, 1),
            ),
            Complaint(
                id="c018",
                report_id="NGD-2026-00118",
                problem_type="garbage",
                confidence=0.92,
                severity="HIGH",
                evidence=["Commercial waste pile spilling across alley"],
                latitude=28.6472,
                longitude=77.1915,
                location_name="Ajmal Khan Market Back Alley, Karol Bagh",
                department="MCD Sanitation & Solid Waste",
                description="Urgent clearing needed for morning market access.",
                image_url="https://images.unsplash.com/photo-1605600659908-0ef719419d41?w=800&auto=format&fit=crop&q=60",
                status="REPORTED",
                duplicate_of=None,
                created_at=dt_off(0, 4),
                updated_at=dt_off(0, 4),
            ),
        ]
        self.complaints = seed_data
        self._report_seq = 119

    def _save_to_storage(self):
        """Saves current state to all configured storage targets."""
        targets = self._get_storage_targets()
        raw_list = [c.model_dump() for c in self.complaints]

        for target in targets:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "w", encoding="utf-8") as f:
                    json.dump(raw_list, f, indent=2, ensure_ascii=False)
                self._last_mtime = target.stat().st_mtime
            except Exception as e:
                logger.warning(f"Failed to persist complaints to {target}: {e}")

    def _check_auto_reload(self):
        """Checks if the shared database on disk was modified by the user site, and reloads."""
        targets = self._get_storage_targets()
        for target in targets:
            if target.exists():
                try:
                    mtime = target.stat().st_mtime
                    if abs(mtime - self._last_mtime) > 0.001:
                        self._load_from_storage()
                        break
                except Exception:
                    pass

    def _notify_user_site_status(self, complaint_id: str, new_status: str):
        """Optionally forwards status change to user site API if configured."""
        if not USER_SITE_API_URL:
            return
        try:
            with httpx.Client(timeout=2.0) as client:
                client.patch(
                    f"{USER_SITE_API_URL}/api/complaints/{complaint_id}/status",
                    json={"status": new_status},
                )
        except Exception as e:
            logger.debug(f"User site API notify skipped or unavailable ({USER_SITE_API_URL}): {e}")

    def reset_demo(self) -> Dict[str, Any]:
        """Resets seed dataset while strictly preserving any real citizen user reports."""
        self._check_auto_reload()
        demo_ids = {f"c{i:03d}" for i in range(1, 19)}
        demo_reps = {f"NGD-2026-{i:05d}" for i in range(101, 119)}

        user_reports = [
            c for c in self.complaints
            if c.id not in demo_ids and c.report_id not in demo_reps
        ]

        self._seed_initial_records()
        self.complaints.extend(user_reports)
        self._save_to_storage()

        return {
            "status": "success",
            "message": "Actual demo complaints reset; citizen user-submitted reports preserved.",
            "demo_count": 16,
            "user_preserved_count": len(user_reports),
        }

    def list_departments(self) -> List[Department]:
        return self.departments

    def list_complaints(
        self,
        problem_type: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        department: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Complaint]:
        self._check_auto_reload()
        results = self.complaints

        if problem_type:
            results = [c for c in results if c.problem_type.lower() == problem_type.lower()]
        if severity:
            results = [c for c in results if c.severity.upper() == severity.upper()]
        if status:
            results = [c for c in results if c.status.upper() == status.upper()]
        if department:
            results = [c for c in results if department.lower() in c.department.lower()]

        # Sort newest first
        results = sorted(results, key=lambda x: x.created_at, reverse=True)

        if limit and limit > 0:
            results = results[:limit]

        return results

    def get_complaint(self, complaint_id: str) -> Optional[Complaint]:
        self._check_auto_reload()
        for c in self.complaints:
            if c.id == complaint_id or c.report_id == complaint_id:
                return c
        return None

    def update_complaint_status(self, complaint_id: str, new_status: ComplaintStatus) -> Optional[Complaint]:
        self._check_auto_reload()
        for c in self.complaints:
            if c.id == complaint_id or c.report_id == complaint_id:
                c.status = new_status
                c.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_to_storage()
                self._notify_user_site_status(c.report_id, new_status)
                return c
        return None

    def add_complaint(self, payload: ComplaintCreate) -> Complaint:
        self._check_auto_reload()

        # If incoming report already exists by report_id, return existing to avoid duplicate entries
        if payload.report_id:
            existing = self.get_complaint(payload.report_id)
            if existing:
                return existing

        now_iso = datetime.now(timezone.utc).isoformat()
        if payload.report_id:
            report_id = payload.report_id
            if report_id.startswith("NGD-2026-"):
                try:
                    seq = int(report_id.split("-")[-1])
                    if seq >= self._report_seq:
                        self._report_seq = seq + 1
                except ValueError:
                    pass
        else:
            report_id = f"NGD-2026-{self._report_seq:05d}"
            self._report_seq += 1

        # Check duplicate within 50 meters for same problem category
        duplicate_report_id = None
        for existing in self.complaints:
            if existing.problem_type == payload.problem_type:
                dist = haversine_distance_meters(
                    payload.latitude, payload.longitude,
                    existing.latitude, existing.longitude
                )
                if dist <= 50.0:
                    duplicate_report_id = existing.report_id
                    break

        new_complaint = Complaint(
            id=payload.id or str(uuid.uuid4()),
            report_id=report_id,
            problem_type=payload.problem_type,
            confidence=payload.confidence,
            severity=payload.severity,
            evidence=payload.evidence,
            latitude=payload.latitude,
            longitude=payload.longitude,
            location_name=payload.location_name,
            department=payload.department,
            description=payload.description,
            image_url=payload.image_url,
            status=payload.status or "REPORTED",
            duplicate_of=duplicate_report_id or payload.duplicate_of,
            citizen_id=payload.citizen_id,
            created_at=now_iso,
            updated_at=now_iso,
        )
        self.complaints.insert(0, new_complaint)
        self._save_to_storage()
        return new_complaint

    def get_heatmap_points(self) -> List[HeatmapPoint]:
        self._check_auto_reload()
        severity_weights = {
            "LOW": 0.35,
            "MEDIUM": 0.60,
            "HIGH": 0.85,
            "CRITICAL": 1.00,
        }
        return [
            HeatmapPoint(
                latitude=c.latitude,
                longitude=c.longitude,
                weight=severity_weights.get(c.severity, 0.5),
                problem_type=c.problem_type,
                severity=c.severity,
                report_id=c.report_id,
            )
            for c in self.complaints
            if c.latitude is not None and c.longitude is not None
        ]

    def get_statistics(self) -> DashboardStatistics:
        self._check_auto_reload()
        total = len(self.complaints)
        high_critical = sum(1 for c in self.complaints if c.severity in ("HIGH", "CRITICAL"))
        pending = sum(1 for c in self.complaints if c.status == "REPORTED")
        in_prog = sum(1 for c in self.complaints if c.status in ("ASSIGNED", "IN_PROGRESS"))
        resolved = sum(1 for c in self.complaints if c.status == "RESOLVED")

        by_category = {"pothole": 0, "garbage": 0, "streetlight": 0, "drain": 0, "other": 0}
        for c in self.complaints:
            by_category[c.problem_type] = by_category.get(c.problem_type, 0) + 1

        by_severity = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for c in self.complaints:
            by_severity[c.severity] = by_severity.get(c.severity, 0) + 1

        by_status = {"REPORTED": 0, "ASSIGNED": 0, "IN_PROGRESS": 0, "RESOLVED": 0}
        for c in self.complaints:
            by_status[c.status] = by_status.get(c.status, 0) + 1

        hotspots = calculate_hotspots(self.complaints)
        daily_trends = calculate_daily_trends(self.complaints)

        return DashboardStatistics(
            total_reports=total,
            high_critical=high_critical,
            pending=pending,
            in_progress=in_prog,
            resolved=resolved,
            by_category=by_category,
            by_severity=by_severity,
            by_status=by_status,
            hotspots=hotspots,
            daily_trends=daily_trends,
        )


# Global singleton instance
data_store = CivicDataStore()
