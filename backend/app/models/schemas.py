from typing import List, Optional, Literal, Dict
from pydantic import BaseModel, Field

ProblemType = Literal["pothole", "garbage", "streetlight", "drain", "other"]
SeverityLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
ComplaintStatus = Literal["REPORTED", "ASSIGNED", "IN_PROGRESS", "RESOLVED"]


class Department(BaseModel):
    id: str
    name: str
    category: str
    is_active: bool = True


class ComplaintCreate(BaseModel):
    problem_type: ProblemType
    confidence: float = 0.92
    severity: SeverityLevel = "MEDIUM"
    evidence: List[str] = Field(default_factory=list)
    latitude: float
    longitude: float
    location_name: str
    department: str
    description: str = ""
    image_url: str = ""
    duplicate_of: Optional[str] = None
    citizen_id: Optional[str] = None


class Complaint(BaseModel):
    id: str
    report_id: str
    problem_type: ProblemType
    confidence: float
    severity: SeverityLevel
    evidence: List[str]
    latitude: float
    longitude: float
    location_name: str
    department: str
    description: str
    image_url: str
    status: ComplaintStatus
    duplicate_of: Optional[str] = None
    citizen_id: Optional[str] = None
    created_at: str
    updated_at: str


class StatusUpdate(BaseModel):
    status: ComplaintStatus


class HotspotInfo(BaseModel):
    id: Optional[str] = None
    title: str
    dominant_issue: str
    total_reports: int
    unresolved_count: int
    high_critical_count: int
    trend_percentage: float
    suggested_action: str
    latitude: float
    longitude: float
    radius_km: float
    repeated_count: Optional[int] = 0
    report_ids: Optional[List[str]] = Field(default_factory=list)


class DailyTrendPoint(BaseModel):
    date: str
    day_label: str
    count: int


class DashboardStatistics(BaseModel):
    total_reports: int
    high_critical: int
    pending: int
    in_progress: int
    resolved: int
    by_category: Dict[str, int]
    by_severity: Dict[str, int]
    by_status: Dict[str, int]
    hotspots: List[HotspotInfo]
    daily_trends: Optional[List[DailyTrendPoint]] = Field(default_factory=list)


class HeatmapPoint(BaseModel):
    latitude: float
    longitude: float
    weight: float
    problem_type: str
    severity: str
    report_id: str
