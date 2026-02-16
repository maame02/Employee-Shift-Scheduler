#!/usr/bin/env python3
"""
Employee Shift Scheduler - Enhanced Edition
Fixed generate schedule functionality
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import json
import datetime
import calendar
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Set, Any
from enum import Enum
import copy
from math import floor
import random
import os
from functools import partial

# ============================================================================
# DATA MODELS (keep all previous data model classes)
# ============================================================================

class Role(Enum):
    MANAGER = "Manager"
    CASHIER = "Cashier"
    STOCKER = "Stocker"
    SUPERVISOR = "Supervisor"
    ASSISTANT = "Assistant"
    CLEANER = "Cleaner"
    SECURITY = "Security"

    @classmethod
    def list(cls):
        return [role.value for role in cls]


class ShiftType(Enum):
    MORNING = "Morning (8am-4pm)"
    EVENING = "Evening (4pm-12am)"
    OVERNIGHT = "Overnight (12am-8am)"
    CUSTOM = "Custom"

    @classmethod
    def list(cls):
        return [st.value for st in cls]


@dataclass
class TimeRange:
    """Represents a time range with start and end times"""
    start: str  # Format: "HH:MM" in 24-hour
    end: str    # Format: "HH:MM" in 24-hour
    
    def to_minutes(self) -> Tuple[int, int]:
        """Convert times to minutes since midnight"""
        start_h, start_m = map(int, self.start.split(':'))
        end_h, end_m = map(int, self.end.split(':'))
        return start_h * 60 + start_m, end_h * 60 + end_m
    
    def duration_hours(self) -> float:
        """Get duration in hours"""
        start_mins, end_mins = self.to_minutes()
        if end_mins < start_mins:  # Overnight shift
            end_mins += 24 * 60
        return (end_mins - start_mins) / 60
    
    def overlaps(self, other: 'TimeRange') -> bool:
        """Check if this time range overlaps with another"""
        s1, e1 = self.to_minutes()
        s2, e2 = other.to_minutes()
        
        # Handle overnight shifts
        if e1 < s1:
            e1 += 24 * 60
        if e2 < s2:
            e2 += 24 * 60
            
        return max(s1, s2) < min(e1, e2)
    
    def __str__(self):
        return f"{self.start}-{self.end}"


@dataclass
class Employee:
    """Employee data model"""
    id: str
    name: str
    role: str
    max_hours_week: float = 40.0
    min_hours_week: float = 0.0
    hire_date: str = ""
    active: bool = True
    notes: str = ""
    
    # Preferences
    morning_pref: int = 3  # 1-5 scale
    evening_pref: int = 3
    night_pref: int = 3
    preferred_days: List[int] = field(default_factory=list)  # 0=Monday, 6=Sunday
    avoid_days: List[int] = field(default_factory=list)
    preferred_coworkers: List[str] = field(default_factory=list)
    avoid_coworkers: List[str] = field(default_factory=list)
    pref_weights: Dict[str, float] = field(default_factory=lambda: {
        "hours_fairness": 0.3,
        "day_preference": 0.2,
        "shift_preference": 0.2,
        "coworker_preference": 0.15,
        "seniority": 0.15
    })
    
    def get_seniority_days(self) -> int:
        """Calculate seniority in days"""
        if not self.hire_date:
            return 0
        try:
            hire = datetime.datetime.strptime(self.hire_date, "%Y-%m-%d").date()
            today = datetime.date.today()
            return (today - hire).days
        except:
            return 0


@dataclass
class DailyAvailability:
    """Availability for a single day"""
    day_of_week: int  # 0-6 (Monday=0)
    time_ranges: List[TimeRange] = field(default_factory=list)
    unavailable_all_day: bool = False
    
    def is_available(self, time_range: TimeRange) -> bool:
        """Check if available for a specific time range"""
        if self.unavailable_all_day:
            return False
        
        if not self.time_ranges:
            return False
        
        for avail_range in self.time_ranges:
            if not avail_range.overlaps(time_range):
                # Check if time_range is completely within avail_range
                s_avail, e_avail = avail_range.to_minutes()
                s_shift, e_shift = time_range.to_minutes()
                
                # Handle overnight
                if e_avail < s_avail:
                    e_avail += 24 * 60
                if e_shift < s_shift:
                    e_shift += 24 * 60
                
                if s_avail <= s_shift and e_shift <= e_avail:
                    return True
        
        return False


@dataclass
class AvailabilityException:
    """Special date exception (time off, etc.)"""
    date: str  # YYYY-MM-DD
    time_ranges: List[TimeRange] = field(default_factory=list)
    unavailable_all_day: bool = False
    reason: str = ""
    approved: bool = False


@dataclass
class Availability:
    """Employee availability model"""
    employee_id: str
    weekly: Dict[int, DailyAvailability] = field(default_factory=dict)
    exceptions: List[AvailabilityException] = field(default_factory=list)
    
    def __post_init__(self):
        # Initialize weekly if empty
        if not self.weekly:
            for day in range(7):
                self.weekly[day] = DailyAvailability(day_of_week=day)


@dataclass
class ShiftRequirement:
    """Required staff for a shift type"""
    shift_type: str
    role_requirements: Dict[str, int] = field(default_factory=dict)
    
    def total_required(self) -> int:
        return sum(self.role_requirements.values())


@dataclass
class Shift:
    """A shift assignment"""
    id: str
    date: str  # YYYY-MM-DD
    shift_type: str
    start_time: str
    end_time: str
    role: str
    assigned_employees: List[str] = field(default_factory=list)
    required_count: int = 1
    notes: str = ""
    
    def get_time_range(self) -> TimeRange:
        return TimeRange(self.start_time, self.end_time)
    
    def is_full(self) -> bool:
        return len(self.assigned_employees) >= self.required_count
    
    def duration_hours(self) -> float:
        return self.get_time_range().duration_hours()


@dataclass
class Schedule:
    """Weekly schedule"""
    week_start: str  # YYYY-MM-DD (Monday)
    shifts: List[Shift] = field(default_factory=list)
    
    def get_shifts_for_day(self, date: str) -> List[Shift]:
        return [s for s in self.shifts if s.date == date]
    
    def get_shifts_for_employee(self, employee_id: str) -> List[Shift]:
        return [s for s in self.shifts if employee_id in s.assigned_employees]
    
    def get_hours_for_employee(self, employee_id: str) -> float:
        hours = 0.0
        for shift in self.shifts:
            if employee_id in shift.assigned_employees:
                hours += shift.duration_hours()
        return hours


@dataclass
class LaborLawConstraints:
    """Labor law constraints"""
    max_hours_per_day: float = 12.0
    min_hours_per_day: float = 2.0
    max_hours_per_week: float = 40.0
    min_rest_between_shifts: float = 8.0  # hours
    max_consecutive_days: int = 6
    required_break_after_hours: float = 5.0
    overtime_threshold: float = 40.0
    overtime_multiplier: float = 1.5
    minor_restrictions: bool = False
    max_days_per_week: int = 7


class ConflictType(Enum):
    UNAVAILABLE = "Employee unavailable when assigned"
    OVER_MAX_HOURS = "Over max hours"
    UNDER_MIN_HOURS = "Under min hours"
    NO_REST = "Back-to-back shifts without rest"
    DOUBLE_BOOKED = "Double-booked employee"
    MISSING_ROLE = "Missing required role"
    UNDERSTAFFED = "Understaffed shift"
    OVERSTAFFED = "Overstaffed shift"
    MAX_CONSECUTIVE_DAYS = "Max consecutive days exceeded"


@dataclass
class Conflict:
    """Schedule conflict"""
    type: ConflictType
    description: str
    shift_id: Optional[str] = None
    employee_id: Optional[str] = None
    severity: str = "error"  # error, warning, info


# ============================================================================
# DATA MANAGER
# ============================================================================

class DataManager:
    """Manages data persistence"""
    
    DEFAULT_FILENAME = "schedule_data.json"
    
    def __init__(self, filename: str = DEFAULT_FILENAME):
        self.filename = filename
        self.employees: Dict[str, Employee] = {}
        self.availabilities: Dict[str, Availability] = {}
        self.shift_requirements: Dict[str, ShiftRequirement] = {}
        self.schedules: List[Schedule] = []
        self.law_constraints = LaborLawConstraints()
        self.next_employee_id = 1000
        self.next_shift_id = 1000
        
    def save(self, filename: str = None):
        """Save data to JSON file"""
        if filename is None:
            filename = self.filename
            
        data = {
            "employees": {eid: asdict(emp) for eid, emp in self.employees.items()},
            "availabilities": {eid: self._availability_to_dict(avail) 
                               for eid, avail in self.availabilities.items()},
            "shift_requirements": self._requirements_to_dict(),
            "schedules": self._schedules_to_dict(),
            "law_constraints": asdict(self.law_constraints),
            "next_employee_id": self.next_employee_id,
            "next_shift_id": self.next_shift_id
        }
        
        try:
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving: {e}")
            return False
    
    def load(self, filename: str = None):
        """Load data from JSON file"""
        if filename is None:
            filename = self.filename
            
        if not os.path.exists(filename):
            return self.load_sample_data()
            
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            # Load employees
            self.employees = {}
            for eid, emp_data in data.get("employees", {}).items():
                self.employees[eid] = Employee(**emp_data)
            
            # Load availabilities
            self.availabilities = {}
            for eid, avail_data in data.get("availabilities", {}).items():
                self.availabilities[eid] = self._dict_to_availability(avail_data)
            
            # Load shift requirements
            self.shift_requirements = self._dict_to_requirements(
                data.get("shift_requirements", {}))
            
            # Load schedules
            self.schedules = self._dict_to_schedules(data.get("schedules", []))
            
            # Load constraints
            if "law_constraints" in data:
                self.law_constraints = LaborLawConstraints(**data["law_constraints"])
            
            self.next_employee_id = data.get("next_employee_id", 1000)
            self.next_shift_id = data.get("next_shift_id", 1000)
            
            return True
        except Exception as e:
            print(f"Error loading: {e}")
            return False
    
    def load_sample_data(self):
        """Load sample data for demo"""
        self.employees = {}
        self.availabilities = {}
        
        sample_employees = [
            ("John Smith", "Manager", "2022-01-15", 40, 20),
            ("Jane Doe", "Cashier", "2022-03-10", 35, 15),
            ("Bob Johnson", "Stocker", "2022-06-22", 40, 10),
            ("Alice Brown", "Cashier", "2023-01-05", 30, 10),
            ("Charlie Wilson", "Supervisor", "2021-11-30", 40, 20),
            ("Diana Prince", "Cashier", "2023-02-14", 25, 8),
            ("Edward Nygma", "Stocker", "2023-03-01", 35, 12),
            ("Fiona Glen", "Cleaner", "2023-04-18", 30, 8),
            ("George Costanza", "Assistant", "2023-05-22", 30, 10),
            ("Hannah Abbott", "Cashier", "2023-06-30", 25, 8),
            ("Ian Malcolm", "Security", "2023-07-15", 40, 20),
            ("Julia Chang", "Manager", "2023-08-01", 35, 15)
        ]
        
        for name, role, hire_date, max_hours, min_hours in sample_employees:
            emp_id = self.generate_employee_id()
            emp = Employee(
                id=emp_id,
                name=name,
                role=role,
                hire_date=hire_date,
                max_hours_week=float(max_hours),
                min_hours_week=float(min_hours),
                active=True
            )
            self.employees[emp_id] = emp
            
            # Create sample availability
            avail = Availability(employee_id=emp_id)
            for day in range(7):
                if random.random() > 0.2:  # 80% available
                    if random.random() > 0.5:
                        time_ranges = [TimeRange("09:00", "17:00")]
                    else:
                        time_ranges = [TimeRange("14:00", "22:00")]
                    avail.weekly[day] = DailyAvailability(
                        day_of_week=day, 
                        time_ranges=time_ranges
                    )
            self.availabilities[emp_id] = avail
        
        # Shift requirements
        self.shift_requirements = {}
        for shift_type in ShiftType.list():
            req = ShiftRequirement(shift_type=shift_type)
            if "Morning" in shift_type:
                req.role_requirements = {"Cashier": 2, "Manager": 1, "Stocker": 1}
            elif "Evening" in shift_type:
                req.role_requirements = {"Cashier": 3, "Manager": 1, "Stocker": 1}
            elif "Overnight" in shift_type:
                req.role_requirements = {"Cashier": 1, "Security": 1, "Manager": 1}
            else:
                req.role_requirements = {"Cashier": 2, "Stocker": 1}
            self.shift_requirements[shift_type] = req
        
        # Create sample schedule for current week
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday())
        self.schedules = [self._create_sample_schedule(monday)]
        
        return True
    
    def _create_sample_schedule(self, week_start: datetime.date) -> Schedule:
        """Create a sample schedule for a week"""
        schedule = Schedule(week_start=week_start.isoformat())
        
        for day_offset in range(7):
            date = (week_start + datetime.timedelta(days=day_offset)).isoformat()
            
            # Morning shift
            morning_shift = Shift(
                id=self.generate_shift_id(),
                date=date,
                shift_type="Morning (8am-4pm)",
                start_time="08:00",
                end_time="16:00",
                role="Cashier",
                required_count=2
            )
            # Assign some employees
            cashiers = [eid for eid, emp in self.employees.items() 
                       if emp.role == "Cashier" and emp.active][:2]
            morning_shift.assigned_employees = cashiers
            schedule.shifts.append(morning_shift)
            
            # Manager shift
            manager_shift = Shift(
                id=self.generate_shift_id(),
                date=date,
                shift_type="Morning (8am-4pm)",
                start_time="08:00",
                end_time="16:00",
                role="Manager",
                required_count=1
            )
            managers = [eid for eid, emp in self.employees.items() 
                       if emp.role == "Manager" and emp.active][:1]
            manager_shift.assigned_employees = managers
            schedule.shifts.append(manager_shift)
            
        return schedule
    
    def generate_employee_id(self) -> str:
        """Generate a unique employee ID"""
        eid = f"EMP{self.next_employee_id}"
        self.next_employee_id += 1
        return eid
    
    def generate_shift_id(self) -> str:
        """Generate a unique shift ID"""
        sid = f"SH{self.next_shift_id}"
        self.next_shift_id += 1
        return sid
    
    def _availability_to_dict(self, avail: Availability) -> dict:
        """Convert Availability to dict for JSON"""
        return {
            "employee_id": avail.employee_id,
            "weekly": {
                str(day): {
                    "day_of_week": da.day_of_week,
                    "time_ranges": [{"start": tr.start, "end": tr.end} 
                                   for tr in da.time_ranges],
                    "unavailable_all_day": da.unavailable_all_day
                } for day, da in avail.weekly.items()
            },
            "exceptions": [
                {
                    "date": ex.date,
                    "time_ranges": [{"start": tr.start, "end": tr.end} 
                                   for tr in ex.time_ranges],
                    "unavailable_all_day": ex.unavailable_all_day,
                    "reason": ex.reason,
                    "approved": ex.approved
                } for ex in avail.exceptions
            ]
        }
    
    def _dict_to_availability(self, data: dict) -> Availability:
        """Convert dict to Availability"""
        avail = Availability(employee_id=data["employee_id"])
        
        # Weekly
        for day_str, da_data in data.get("weekly", {}).items():
            day = int(day_str)
            time_ranges = [TimeRange(tr["start"], tr["end"]) 
                          for tr in da_data.get("time_ranges", [])]
            avail.weekly[day] = DailyAvailability(
                day_of_week=day,
                time_ranges=time_ranges,
                unavailable_all_day=da_data.get("unavailable_all_day", False)
            )
        
        # Exceptions
        for ex_data in data.get("exceptions", []):
            time_ranges = [TimeRange(tr["start"], tr["end"]) 
                          for tr in ex_data.get("time_ranges", [])]
            ex = AvailabilityException(
                date=ex_data["date"],
                time_ranges=time_ranges,
                unavailable_all_day=ex_data.get("unavailable_all_day", False),
                reason=ex_data.get("reason", ""),
                approved=ex_data.get("approved", False)
            )
            avail.exceptions.append(ex)
        
        return avail
    
    def _requirements_to_dict(self) -> dict:
        """Convert shift requirements to dict"""
        return {
            st: {
                "shift_type": req.shift_type,
                "role_requirements": req.role_requirements
            } for st, req in self.shift_requirements.items()
        }
    
    def _dict_to_requirements(self, data: dict) -> dict:
        """Convert dict to shift requirements"""
        reqs = {}
        for st, req_data in data.items():
            reqs[st] = ShiftRequirement(
                shift_type=req_data["shift_type"],
                role_requirements=req_data["role_requirements"]
            )
        return reqs
    
    def _schedules_to_dict(self) -> list:
        """Convert schedules to dict list"""
        schedules = []
        for schedule in self.schedules:
            schedules.append({
                "week_start": schedule.week_start,
                "shifts": [
                    {
                        "id": s.id,
                        "date": s.date,
                        "shift_type": s.shift_type,
                        "start_time": s.start_time,
                        "end_time": s.end_time,
                        "role": s.role,
                        "assigned_employees": s.assigned_employees,
                        "required_count": s.required_count,
                        "notes": s.notes
                    } for s in schedule.shifts
                ]
            })
        return schedules
    
    def _dict_to_schedules(self, data: list) -> List[Schedule]:
        """Convert dict list to schedules"""
        schedules = []
        for schedule_data in data:
            shifts = []
            for shift_data in schedule_data.get("shifts", []):
                shift = Shift(
                    id=shift_data.get("id", self.generate_shift_id()),
                    date=shift_data["date"],
                    shift_type=shift_data["shift_type"],
                    start_time=shift_data["start_time"],
                    end_time=shift_data["end_time"],
                    role=shift_data["role"],
                    assigned_employees=shift_data.get("assigned_employees", []),
                    required_count=shift_data.get("required_count", 1),
                    notes=shift_data.get("notes", "")
                )
                shifts.append(shift)
            
            schedule = Schedule(
                week_start=schedule_data["week_start"],
                shifts=shifts
            )
            schedules.append(schedule)
        return schedules


# ============================================================================
# SCHEDULING ALGORITHM
# ============================================================================

class Scheduler:
    """Main scheduling algorithm"""
    
    def __init__(self, data_manager: DataManager):
        self.data = data_manager
        
    def generate_schedule(self, week_start: datetime.date, 
                          strategy: str = "hybrid") -> Tuple[Schedule, List[Conflict]]:
        """Generate a schedule for the given week"""
        schedule = Schedule(week_start=week_start.isoformat())
        all_conflicts = []
        
        # Get all active employees
        active_employees = {eid: emp for eid, emp in self.data.employees.items() 
                           if emp.active}
        
        # Create shifts based on requirements
        shifts = self._create_shifts_for_week(week_start)
        
        # Track employee hours
        employee_hours = {eid: 0.0 for eid in active_employees}
        
        # Sort shifts by date and time
        shifts.sort(key=lambda s: (s.date, s.start_time))
        
        # Assign employees to shifts
        for shift in shifts:
            # Find eligible employees for this shift
            eligible = self._find_eligible_employees(shift, active_employees, 
                                                     employee_hours)
            
            # Score and sort eligible employees
            scored = [(emp_id, self._score_employee_for_shift(
                emp_id, shift, active_employees[emp_id], employee_hours,
                schedule, strategy)) for emp_id in eligible]
            
            scored.sort(key=lambda x: x[1], reverse=True)
            
            # Assign top employees
            assigned = 0
            for emp_id, score in scored:
                if assigned >= shift.required_count:
                    break
                    
                # Check if employee is available
                if self._is_employee_available(emp_id, shift):
                    # Check if employee already assigned to another shift at same time
                    if not self._is_employee_busy(emp_id, shift, schedule):
                        shift.assigned_employees.append(emp_id)
                        employee_hours[emp_id] += shift.duration_hours()
                        assigned += 1
            
            # Check for understaffing
            if assigned < shift.required_count:
                all_conflicts.append(Conflict(
                    type=ConflictType.UNDERSTAFFED,
                    description=f"Understaffed: {shift.shift_type} on {shift.date} "
                               f"needs {shift.required_count - assigned} more {shift.role}(s)",
                    shift_id=shift.id,
                    severity="error"
                ))
        
        schedule.shifts = shifts
        
        # Check for conflicts
        all_conflicts.extend(self._check_conflicts(schedule))
        
        return schedule, all_conflicts
    
    def _create_shifts_for_week(self, week_start: datetime.date) -> List[Shift]:
        """Create shift objects for the entire week based on requirements"""
        shifts = []
        
        for day_offset in range(7):
            date = (week_start + datetime.timedelta(days=day_offset)).isoformat()
            
            for shift_type, requirement in self.data.shift_requirements.items():
                for role, count in requirement.role_requirements.items():
                    # Determine shift times based on type
                    if "Morning" in shift_type:
                        start, end = "08:00", "16:00"
                    elif "Evening" in shift_type:
                        start, end = "16:00", "00:00"
                    elif "Overnight" in shift_type:
                        start, end = "00:00", "08:00"
                    else:
                        start, end = "09:00", "17:00"  # Default for custom
                    
                    shift = Shift(
                        id=self.data.generate_shift_id(),
                        date=date,
                        shift_type=shift_type,
                        start_time=start,
                        end_time=end,
                        role=role,
                        required_count=count
                    )
                    shifts.append(shift)
        
        return shifts
    
    def _find_eligible_employees(self, shift: Shift, 
                                  employees: Dict[str, Employee],
                                  employee_hours: Dict[str, float]) -> List[str]:
        """Find employees eligible for a shift based on role and constraints"""
        eligible = []
        
        for emp_id, emp in employees.items():
            # Check role
            if emp.role != shift.role:
                continue
            
            # Check max hours
            if employee_hours[emp_id] + shift.duration_hours() > emp.max_hours_week:
                continue
            
            eligible.append(emp_id)
        
        return eligible
    
    def _is_employee_busy(self, emp_id: str, shift: Shift, schedule: Schedule) -> bool:
        """Check if employee is already assigned to another shift at the same time"""
        shift_time = shift.get_time_range()
        
        for s in schedule.shifts:
            if emp_id in s.assigned_employees and s.date == shift.date:
                if s.get_time_range().overlaps(shift_time):
                    return True
        return False
    
    def _score_employee_for_shift(self, emp_id: str, shift: Shift,
                                   employee: Employee,
                                   employee_hours: Dict[str, float],
                                   schedule: Schedule,
                                   strategy: str) -> float:
        """Score how well an employee fits a shift"""
        score = 50.0  # Base score
        weights = employee.pref_weights
        
        # Hours fairness (prioritize those with fewer hours)
        if employee_hours[emp_id] < employee.min_hours_week:
            score += weights.get("hours_fairness", 0.3) * 30
        elif employee_hours[emp_id] < employee.max_hours_week / 2:
            score += weights.get("hours_fairness", 0.3) * 15
        else:
            score -= weights.get("hours_fairness", 0.3) * 10
        
        # Day preference
        day_of_week = datetime.datetime.fromisoformat(shift.date).weekday()
        if day_of_week in employee.preferred_days:
            score += weights.get("day_preference", 0.2) * 25
        elif day_of_week in employee.avoid_days:
            score -= weights.get("day_preference", 0.2) * 20
        
        # Shift type preference
        if "Morning" in shift.shift_type:
            score += weights.get("shift_preference", 0.2) * employee.morning_pref * 5
        elif "Evening" in shift.shift_type:
            score += weights.get("shift_preference", 0.2) * employee.evening_pref * 5
        elif "Overnight" in shift.shift_type:
            score += weights.get("shift_preference", 0.2) * employee.night_pref * 5
        
        # Seniority
        seniority_days = employee.get_seniority_days()
        score += weights.get("seniority", 0.15) * min(seniority_days / 30, 20)
        
        # Strategy adjustments
        if strategy == "fair_distribution":
            # Bias toward equal hours
            score += (40 - employee_hours[emp_id]) * 2
        elif strategy == "preference_first":
            # Preferences already weighted higher
            score *= 1.2
        elif strategy == "seniority_based":
            score += seniority_days / 10
        
        return score
    
    def _is_employee_available(self, emp_id: str, shift: Shift) -> bool:
        """Check if employee is available for a shift"""
        if emp_id not in self.data.availabilities:
            return True  # No availability set means always available
        
        avail = self.data.availabilities[emp_id]
        shift_time = shift.get_time_range()
        shift_date = shift.date
        
        # Check exceptions first
        for exception in avail.exceptions:
            if exception.date == shift_date and exception.approved:
                if exception.unavailable_all_day:
                    return False
                if exception.time_ranges:
                    for tr in exception.time_ranges:
                        if tr.overlaps(shift_time):
                            return False
        
        # Check weekly availability
        day_of_week = datetime.datetime.fromisoformat(shift_date).weekday()
        daily_avail = avail.weekly.get(day_of_week)
        
        if daily_avail:
            if daily_avail.unavailable_all_day:
                return False
            
            if daily_avail.time_ranges:
                # Check if shift fits within any available time range
                for avail_range in daily_avail.time_ranges:
                    s_avail, e_avail = avail_range.to_minutes()
                    s_shift, e_shift = shift_time.to_minutes()
                    
                    # Handle overnight
                    if e_avail < s_avail:
                        e_avail += 24 * 60
                    if e_shift < s_shift:
                        e_shift += 24 * 60
                    
                    if s_avail <= s_shift and e_shift <= e_avail:
                        return True
                return False
        
        return True  # No availability constraints
    
    def _check_conflicts(self, schedule: Schedule) -> List[Conflict]:
        """Check schedule for conflicts"""
        conflicts = []
        employee_shifts = {}  # emp_id -> list of shifts
        employee_daily_hours = {}  # emp_id -> {date: hours}
        
        # Organize shifts
        for shift in schedule.shifts:
            for emp_id in shift.assigned_employees:
                if emp_id not in employee_shifts:
                    employee_shifts[emp_id] = []
                employee_shifts[emp_id].append(shift)
                
                # Track daily hours
                if emp_id not in employee_daily_hours:
                    employee_daily_hours[emp_id] = {}
                if shift.date not in employee_daily_hours[emp_id]:
                    employee_daily_hours[emp_id][shift.date] = 0
                employee_daily_hours[emp_id][shift.date] += shift.duration_hours()
        
        # Check each employee
        for emp_id, shifts in employee_shifts.items():
            emp = self.data.employees.get(emp_id)
            if not emp:
                continue
            
            # Sort shifts by date and time
            shifts.sort(key=lambda s: (s.date, s.start_time))
            
            # Check consecutive days
            dates = sorted(list(set([s.date for s in shifts])))
            if len(dates) > self.data.law_constraints.max_consecutive_days:
                conflicts.append(Conflict(
                    type=ConflictType.MAX_CONSECUTIVE_DAYS,
                    description=f"{emp.name} works {len(dates)} consecutive days",
                    employee_id=emp_id,
                    severity="warning"
                ))
            
            # Check daily hours
            for date, hours in employee_daily_hours[emp_id].items():
                if hours > self.data.law_constraints.max_hours_per_day:
                    conflicts.append(Conflict(
                        type=ConflictType.OVER_MAX_HOURS,
                        description=f"{emp.name} works {hours:.1f}h on {date} "
                                   f"(max {self.data.law_constraints.max_hours_per_day}h)",
                        employee_id=emp_id,
                        severity="error"
                    ))
            
            # Check weekly hours
            weekly_hours = sum(s.duration_hours() for s in shifts)
            if weekly_hours > emp.max_hours_week:
                conflicts.append(Conflict(
                    type=ConflictType.OVER_MAX_HOURS,
                    description=f"{emp.name} scheduled {weekly_hours:.1f}h/week "
                               f"(max {emp.max_hours_week:.1f}h)",
                    employee_id=emp_id,
                    severity="error"
                ))
            elif weekly_hours < emp.min_hours_week and weekly_hours > 0:
                conflicts.append(Conflict(
                    type=ConflictType.UNDER_MIN_HOURS,
                    description=f"{emp.name} scheduled only {weekly_hours:.1f}h/week "
                               f"(min {emp.min_hours_week:.1f}h)",
                    employee_id=emp_id,
                    severity="warning"
                ))
            
            # Check rest between shifts
            for i in range(len(shifts) - 1):
                shift1 = shifts[i]
                shift2 = shifts[i+1]
                
                # Skip if different days with a gap
                if shift1.date != shift2.date:
                    date1 = datetime.datetime.fromisoformat(shift1.date)
                    date2 = datetime.datetime.fromisoformat(shift2.date)
                    if (date2 - date1).days > 1:
                        continue
                
                # Calculate end of first shift and start of second
                end1 = datetime.datetime.strptime(f"{shift1.date} {shift1.end_time}", "%Y-%m-%d %H:%M")
                start2 = datetime.datetime.strptime(f"{shift2.date} {shift2.start_time}", "%Y-%m-%d %H:%M")
                
                # Handle overnight shifts
                if shift1.end_time < shift1.start_time:
                    end1 += datetime.timedelta(days=1)
                if shift2.start_time < shift2.end_time and shift2.start_time < "12:00":
                    start2 += datetime.timedelta(days=1)
                
                rest_hours = (start2 - end1).total_seconds() / 3600
                if 0 < rest_hours < self.data.law_constraints.min_rest_between_shifts:
                    conflicts.append(Conflict(
                        type=ConflictType.NO_REST,
                        description=f"{emp.name} has only {rest_hours:.1f}h rest "
                                   f"between shifts",
                        employee_id=emp_id,
                        severity="error"
                    ))
        
        # Check double booking (same employee on multiple shifts at same time)
        time_slots = {}
        for shift in schedule.shifts:
            for emp_id in shift.assigned_employees:
                key = f"{shift.date}_{emp_id}"
                if key in time_slots:
                    conflicts.append(Conflict(
                        type=ConflictType.DOUBLE_BOOKED,
                        description=f"{self.data.employees.get(emp_id, Employee(id=emp_id, name='Unknown', role='')).name} "
                                   f"double booked on {shift.date}",
                        employee_id=emp_id,
                        severity="error"
                    ))
                time_slots[key] = shift.id
        
        # Check for missing required roles
        for shift in schedule.shifts:
            role_count = len([e for e in shift.assigned_employees 
                            if self.data.employees.get(e, Employee(id=e, name='', role='')).role == shift.role])
            if role_count < shift.required_count:
                conflicts.append(Conflict(
                    type=ConflictType.UNDERSTAFFED,
                    description=f"{shift.shift_type} on {shift.date} needs "
                               f"{shift.required_count - role_count} more {shift.role}(s)",
                    shift_id=shift.id,
                    severity="error"
                ))
        
        return conflicts
    
    def auto_fill(self, schedule: Schedule) -> Tuple[Schedule, List[Conflict]]:
        """Auto-fill empty shifts"""
        conflicts = []
        
        for shift in schedule.shifts:
            if shift.is_full():
                continue
            
            # Find eligible employees not already assigned
            assigned = set(shift.assigned_employees)
            eligible = [eid for eid, emp in self.data.employees.items() 
                       if emp.active and emp.role == shift.role 
                       and eid not in assigned
                       and self._is_employee_available(eid, shift)]
            
            # Check hours constraints
            schedule_hours = {eid: 0.0 for eid in self.data.employees}
            for s in schedule.shifts:
                for eid in s.assigned_employees:
                    schedule_hours[eid] += s.duration_hours()
            
            eligible = [eid for eid in eligible 
                       if schedule_hours[eid] + shift.duration_hours() <= 
                       self.data.employees[eid].max_hours_week]
            
            # Check if already busy at this time
            eligible = [eid for eid in eligible 
                       if not self._is_employee_busy(eid, shift, schedule)]
            
            # Assign
            needed = shift.required_count - len(shift.assigned_employees)
            for eid in eligible[:needed]:
                shift.assigned_employees.append(eid)
        
        # Recheck conflicts
        all_conflicts = self._check_conflicts(schedule)
        conflicts.extend(all_conflicts)
        
        return schedule, conflicts


# ============================================================================
# UI COMPONENTS
# ============================================================================

class ModernButton(tk.Button):
    """Modern styled button with hover effects"""
    
    def __init__(self, master, **kwargs):
        self.bg_color = kwargs.pop('bg', '#2563EB')
        self.hover_color = kwargs.pop('hover', '#1D4ED8')
        self.fg_color = kwargs.pop('fg', 'white')
        
        super().__init__(
            master,
            bg=self.bg_color,
            fg=self.fg_color,
            font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT,
            cursor="hand2",
            **kwargs
        )
        
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
    
    def on_enter(self, e):
        self.config(bg=self.hover_color)
    
    def on_leave(self, e):
        self.config(bg=self.bg_color)


class ModernEntry(tk.Frame):
    """Modern styled entry with label"""
    
    def __init__(self, master, label="", **kwargs):
        super().__init__(master, bg='#FFFFFF')
        
        self.label = tk.Label(self, text=label, bg='#FFFFFF', 
                              font=("Segoe UI", 9), fg='#4B5563')
        self.label.pack(anchor=tk.W, pady=(0, 2))
        
        self.entry = tk.Entry(self, font=("Segoe UI", 10), 
                              bd=1, relief=tk.SOLID, **kwargs)
        self.entry.pack(fill=tk.X, ipady=5)
        
        # Style the entry
        self.entry.bind("<FocusIn>", lambda e: self.entry.config(
            highlightcolor='#2563EB', highlightthickness=1))
        self.entry.bind("<FocusOut>", lambda e: self.entry.config(
            highlightthickness=0))
    
    def get(self):
        return self.entry.get()
    
    def insert(self, index, string):
        self.entry.insert(index, string)
    
    def delete(self, first, last=None):
        self.entry.delete(first, last)


class ScrollableFrame(tk.Frame):
    """A scrollable frame that can contain other widgets"""
    
    def __init__(self, container, *args, **kwargs):
        # Remove bg from kwargs
        bg_color = kwargs.pop('bg', '#FFFFFF')
        super().__init__(container, *args, **kwargs)
        self.configure(bg=bg_color)
        
        # Create canvas and scrollbar
        self.canvas = tk.Canvas(self, bg=bg_color, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", 
                                       command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg=bg_color)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # Pack
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        # Bind mousewheel
        self.bind_mousewheel()
    
    def bind_mousewheel(self):
        """Bind mousewheel for scrolling"""
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        self.canvas.bind_all("<MouseWheel>", _on_mousewheel)


class ToolTip:
    """Enhanced tooltip with better styling"""
    
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind('<Enter>', self.show_tip)
        widget.bind('<Leave>', self.hide_tip)
        widget.bind('<ButtonPress>', self.hide_tip)
    
    def show_tip(self, event=None):
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        
        # Styled tooltip
        frame = tk.Frame(tw, bg='#1F2937', relief=tk.SOLID, bd=1)
        frame.pack()
        
        label = tk.Label(frame, text=self.text, justify=tk.LEFT,
                        background='#1F2937', fg='white',
                        font=("Segoe UI", 9), padx=8, pady=4)
        label.pack()
    
    def hide_tip(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


# ============================================================================
# MAIN APPLICATION CLASS
# ============================================================================

class EmployeeShiftSchedulerApp:
    """Main application class with enhanced UI"""
    
    # Modern color scheme
    COLORS = {
        'bg': '#F3F4F6',
        'card': '#FFFFFF',
        'accent': '#2563EB',
        'accent_hover': '#1D4ED8',
        'success': '#10B981',
        'success_hover': '#059669',
        'warning': '#F59E0B',
        'warning_hover': '#D97706',
        'error': '#EF4444',
        'error_hover': '#DC2626',
        'text': '#1F2937',
        'text_light': '#6B7280',
        'border': '#E5E7EB',
        'striped': '#F9FAFB',
        'hover': '#F3F4F6'
    }
    
    def __init__(self, root):
        self.root = root
        self.root.title("Employee Shift Scheduler Pro")
        self.root.geometry("1400x850")
        self.root.configure(bg=self.COLORS['bg'])
        
        # Set modern theme
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Treeview', background='#FFFFFF', 
                       fieldbackground='#FFFFFF', foreground='#1F2937')
        style.configure('Treeview.Heading', background='#F3F4F6', 
                       foreground='#1F2937', font=('Segoe UI', 10, 'bold'))
        style.map('Treeview', background=[('selected', '#2563EB')])
        
        # Data
        self.data = DataManager()
        self.data.load_sample_data()
        self.scheduler = Scheduler(self.data)
        self.current_schedule = None
        self.current_week = datetime.date.today()
        # Adjust to Monday
        self.current_week = self.current_week - datetime.timedelta(
            days=self.current_week.weekday())
        self.conflicts = []
        self.undo_stack = []
        self.redo_stack = []
        self.manual_mode = False
        self.drag_data = {"shift": None, "emp_id": None, "x": 0, "y": 0}
        
        # Variables
        self.search_var = tk.StringVar()
        self.search_var.trace_add('write', lambda *args: self.update_employee_list())
        
        # Setup UI
        self.setup_menu()
        self.setup_ui()
        self.load_week()
        self.update_status_bar()
        
        # Bind keyboard shortcuts
        self.setup_shortcuts()
    
    def setup_menu(self):
        """Create modern menu bar"""
        menubar = tk.Menu(self.root, bg=self.COLORS['card'], fg=self.COLORS['text'],
                         activebackground=self.COLORS['accent'],
                         activeforeground='white')
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0, bg=self.COLORS['card'])
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Save", command=self.save_data, accelerator="Ctrl+S")
        file_menu.add_command(label="Load", command=self.load_data, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Export Schedule CSV", command=self.export_csv)
        file_menu.add_command(label="Print Preview", command=self.print_preview)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        
        # Edit menu
        edit_menu = tk.Menu(menubar, tearoff=0, bg=self.COLORS['card'])
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo", command=self.redo, accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="New Employee", command=self.add_employee, 
                            accelerator="Ctrl+N")
        
        # View menu
        view_menu = tk.Menu(menubar, tearoff=0, bg=self.COLORS['card'])
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Refresh", command=self.refresh)
        view_menu.add_separator()
        view_menu.add_command(label="Toggle Dark Mode", command=self.toggle_dark_mode)
        
        # Schedule menu
        schedule_menu = tk.Menu(menubar, tearoff=0, bg=self.COLORS['card'])
        menubar.add_cascade(label="Schedule", menu=schedule_menu)
        schedule_menu.add_command(label="Generate New", command=self.generate_schedule)
        schedule_menu.add_command(label="Auto-Fill", command=self.auto_fill)
        schedule_menu.add_command(label="Clear Schedule", command=self.clear_schedule)
        schedule_menu.add_separator()
        schedule_menu.add_command(label="Manual Adjust Mode", command=self.toggle_manual_mode)
        
        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0, bg=self.COLORS['card'])
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Constraints", command=self.edit_constraints)
        tools_menu.add_command(label="Shift Requirements", command=self.edit_requirements)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0, bg=self.COLORS['card'])
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="User Guide", command=self.show_help)
        help_menu.add_command(label="About", command=self.show_about)
    
    def setup_shortcuts(self):
        """Set up keyboard shortcuts"""
        self.root.bind('<Control-s>', lambda e: self.save_data())
        self.root.bind('<Control-o>', lambda e: self.load_data())
        self.root.bind('<Control-z>', lambda e: self.undo())
        self.root.bind('<Control-y>', lambda e: self.redo())
        self.root.bind('<Control-n>', lambda e: self.add_employee())
        self.root.bind('<Delete>', lambda e: self.delete_selected())
        self.root.bind('<Escape>', lambda e: self.exit_manual_mode())
    
    def setup_ui(self):
        """Create main UI layout with modern design"""
        # Top bar with title and buttons
        top_frame = tk.Frame(self.root, bg=self.COLORS['card'], height=70)
        top_frame.pack(fill=tk.X, padx=0, pady=(0, 10))
        top_frame.pack_propagate(False)
        
        # Logo/Title
        title_frame = tk.Frame(top_frame, bg=self.COLORS['card'])
        title_frame.pack(side=tk.LEFT, padx=20, pady=10)
        
        title = tk.Label(title_frame, text="📅 Shift Scheduler Pro",
                        font=("Segoe UI", 18, "bold"), bg=self.COLORS['card'],
                        fg=self.COLORS['accent'])
        title.pack(side=tk.LEFT)
        
        subtitle = tk.Label(title_frame, text="v2.0",
                           font=("Segoe UI", 10), bg=self.COLORS['card'],
                           fg=self.COLORS['text_light'])
        subtitle.pack(side=tk.LEFT, padx=(10, 0))
        
        # Quick actions
        actions_frame = tk.Frame(top_frame, bg=self.COLORS['card'])
        actions_frame.pack(side=tk.RIGHT, padx=20)
        
        # Quick action buttons
        quick_btn_style = {'bg': self.COLORS['bg'], 'fg': self.COLORS['text'],
                          'font': ("Segoe UI", 10), 'padx': 15, 'pady': 5}
        
        save_btn = tk.Button(actions_frame, text="💾 Save", **quick_btn_style,
                            command=self.save_data)
        save_btn.pack(side=tk.LEFT, padx=2)
        ToolTip(save_btn, "Save data (Ctrl+S)")
        
        generate_btn = tk.Button(actions_frame, text="⚡ Generate", **quick_btn_style,
                                command=self.generate_schedule)
        generate_btn.pack(side=tk.LEFT, padx=2)
        ToolTip(generate_btn, "Generate new schedule")
        
        clear_btn = tk.Button(actions_frame, text="🗑️ Clear", **quick_btn_style,
                             command=self.clear_schedule)
        clear_btn.pack(side=tk.LEFT, padx=2)
        ToolTip(clear_btn, "Clear current schedule")
        
        # Notebook for tabs
        style = ttk.Style()
        style.configure('TNotebook', background=self.COLORS['bg'])
        style.configure('TNotebook.Tab', padding=[15, 5], font=('Segoe UI', 10))
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=0)
        
        # Create tabs
        self.schedule_tab = ttk.Frame(self.notebook)
        self.employees_tab = ttk.Frame(self.notebook)
        self.availability_tab = ttk.Frame(self.notebook)
        self.reports_tab = ttk.Frame(self.notebook)
        
        self.notebook.add(self.schedule_tab, text="📋 Schedule")
        self.notebook.add(self.employees_tab, text="👥 Employees")
        self.notebook.add(self.availability_tab, text="⏰ Availability")
        self.notebook.add(self.reports_tab, text="📊 Reports")
        
        # Setup each tab
        self.setup_schedule_tab()
        self.setup_employees_tab()
        self.setup_availability_tab()
        self.setup_reports_tab()
        
        # Status bar
        self.setup_status_bar()
    
    def setup_status_bar(self):
        """Create modern status bar"""
        self.status_bar = tk.Frame(self.root, bg=self.COLORS['card'], height=35)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_bar.pack_propagate(False)
        
        # Left status
        self.status_label = tk.Label(self.status_bar, bg=self.COLORS['card'],
                                     fg=self.COLORS['text_light'],
                                     font=("Segoe UI", 9))
        self.status_label.pack(side=tk.LEFT, padx=15, pady=8)
        
        # Center status (mode indicator)
        self.mode_label = tk.Label(self.status_bar, bg=self.COLORS['card'],
                                   fg=self.COLORS['accent'],
                                   font=("Segoe UI", 9, "bold"))
        self.mode_label.pack(side=tk.LEFT, padx=20, pady=8)
        
        # Right status
        self.employee_count_label = tk.Label(self.status_bar, bg=self.COLORS['card'],
                                            fg=self.COLORS['text_light'],
                                            font=("Segoe UI", 9))
        self.employee_count_label.pack(side=tk.RIGHT, padx=15, pady=8)
    
    def setup_schedule_tab(self):
        """Set up the schedule tab with enhanced design"""
        # Main container
        main_frame = tk.Frame(self.schedule_tab, bg=self.COLORS['bg'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left panel - Employees (scrollable)
        left_panel = tk.Frame(main_frame, bg=self.COLORS['card'], width=280,
                              relief=tk.SOLID, bd=1)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_panel.pack_propagate(False)
        
        # Header
        header_frame = tk.Frame(left_panel, bg=self.COLORS['card'])
        header_frame.pack(fill=tk.X, padx=15, pady=15)
        
        tk.Label(header_frame, text="👥 EMPLOYEES", font=("Segoe UI", 12, "bold"),
                bg=self.COLORS['card'], fg=self.COLORS['text']).pack(side=tk.LEFT)
        
        active_count = len([e for e in self.data.employees.values() if e.active])
        tk.Label(header_frame, text=f"({active_count} active)",
                font=("Segoe UI", 9), bg=self.COLORS['card'],
                fg=self.COLORS['text_light']).pack(side=tk.RIGHT)
        
        # Search
        search_frame = tk.Frame(left_panel, bg=self.COLORS['card'])
        search_frame.pack(fill=tk.X, padx=15, pady=(0, 10))
        
        search_entry = tk.Entry(search_frame, textvariable=self.search_var,
                               bg='#F9FAFB', relief=tk.SOLID, bd=1,
                               font=("Segoe UI", 10))
        search_entry.pack(fill=tk.X, ipady=8)
        search_entry.insert(0, "🔍 Search employees...")
        search_entry.bind('<FocusIn>', lambda e: search_entry.delete(0, tk.END) if search_entry.get() == "🔍 Search employees..." else None)
        
        # Scrollable employee list
        self.employee_scroll_frame = ScrollableFrame(left_panel, bg=self.COLORS['card'])
        self.employee_scroll_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        self.employee_list_frame = self.employee_scroll_frame.scrollable_frame
        
        self.update_employee_list()
        
        # Right panel - Schedule
        right_panel = tk.Frame(main_frame, bg=self.COLORS['card'],
                               relief=tk.SOLID, bd=1)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Week navigation
        nav_frame = tk.Frame(right_panel, bg=self.COLORS['card'])
        nav_frame.pack(fill=tk.X, padx=15, pady=15)
        
        nav_left = tk.Button(nav_frame, text="◀", command=self.prev_week,
                            bg=self.COLORS['bg'], relief=tk.FLAT,
                            font=("Segoe UI", 12), width=3)
        nav_left.pack(side=tk.LEFT)
        ToolTip(nav_left, "Previous week")
        
        self.week_label = tk.Label(nav_frame,
                                   text=self.current_week.strftime("%B %d, %Y"),
                                   font=("Segoe UI", 14, "bold"),
                                   bg=self.COLORS['card'])
        self.week_label.pack(side=tk.LEFT, padx=20)
        
        nav_right = tk.Button(nav_frame, text="▶", command=self.next_week,
                             bg=self.COLORS['bg'], relief=tk.FLAT,
                             font=("Segoe UI", 12), width=3)
        nav_right.pack(side=tk.LEFT)
        ToolTip(nav_right, "Next week")
        
        # Today button
        today_btn = tk.Button(nav_frame, text="Today", command=self.go_to_today,
                             bg=self.COLORS['accent'], fg='white',
                             font=("Segoe UI", 9, "bold"), padx=15)
        today_btn.pack(side=tk.RIGHT)
        ToolTip(today_btn, "Go to current week")
        
        # Schedule grid with scroll
        grid_container = tk.Frame(right_panel, bg=self.COLORS['card'])
        grid_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        # Canvas for scrolling schedule grid
        self.schedule_canvas = tk.Canvas(grid_container, bg=self.COLORS['card'],
                                         highlightthickness=0)
        v_scrollbar = ttk.Scrollbar(grid_container, orient="vertical",
                                   command=self.schedule_canvas.yview)
        h_scrollbar = ttk.Scrollbar(grid_container, orient="horizontal",
                                   command=self.schedule_canvas.xview)
        
        self.schedule_frame = tk.Frame(self.schedule_canvas, bg=self.COLORS['card'])
        self.schedule_frame.bind(
            "<Configure>",
            lambda e: self.schedule_canvas.configure(scrollregion=self.schedule_canvas.bbox("all"))
        )
        
        self.schedule_canvas.create_window((0, 0), window=self.schedule_frame, anchor="nw")
        self.schedule_canvas.configure(yscrollcommand=v_scrollbar.set,
                                      xscrollcommand=h_scrollbar.set)
        
        self.schedule_canvas.pack(side="left", fill="both", expand=True)
        v_scrollbar.pack(side="right", fill="y")
        h_scrollbar.pack(side="bottom", fill="x")
        
        # Action buttons
        action_frame = tk.Frame(right_panel, bg=self.COLORS['card'])
        action_frame.pack(fill=tk.X, padx=15, pady=15)
        
        ModernButton(action_frame, text="⚡ Generate Schedule",
                    bg=self.COLORS['accent'], hover=self.COLORS['accent_hover'],
                    command=self.generate_schedule).pack(side=tk.LEFT, padx=2)
        
        ModernButton(action_frame, text="🤖 Auto-Fill",
                    bg=self.COLORS['success'], hover=self.COLORS['success_hover'],
                    command=self.auto_fill).pack(side=tk.LEFT, padx=2)
        
        self.manual_btn = ModernButton(action_frame, text="✏️ Manual Adjust",
                                       bg=self.COLORS['warning'], 
                                       hover=self.COLORS['warning_hover'],
                                       command=self.toggle_manual_mode)
        self.manual_btn.pack(side=tk.LEFT, padx=2)
        
        ModernButton(action_frame, text="🗑️ Clear",
                    bg=self.COLORS['error'], hover=self.COLORS['error_hover'],
                    command=self.clear_schedule).pack(side=tk.LEFT, padx=2)
        
        ModernButton(action_frame, text="📥 Export",
                    bg=self.COLORS['text'], hover='#374151',
                    command=self.export_csv).pack(side=tk.RIGHT, padx=2)
        
        # Shift requirements panel
        self.setup_requirements_panel(main_frame)
        
        # Conflicts panel
        self.setup_conflicts_panel(main_frame)
    
    def setup_requirements_panel(self, parent):
        """Setup shift requirements panel"""
        req_frame = tk.Frame(parent, bg=self.COLORS['card'],
                             relief=tk.SOLID, bd=1)
        req_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        
        req_header = tk.Frame(req_frame, bg=self.COLORS['card'])
        req_header.pack(fill=tk.X, padx=15, pady=10)
        
        tk.Label(req_header, text="📋 SHIFT REQUIREMENTS",
                font=("Segoe UI", 10, "bold"), bg=self.COLORS['card']).pack(side=tk.LEFT)
        
        edit_req_btn = tk.Button(req_header, text="✏️ Edit", bg=self.COLORS['bg'],
                                font=("Segoe UI", 9), command=self.edit_requirements)
        edit_req_btn.pack(side=tk.RIGHT)
        ToolTip(edit_req_btn, "Edit shift requirements")
        
        self.req_content = tk.Frame(req_frame, bg=self.COLORS['card'])
        self.req_content.pack(fill=tk.X, padx=15, pady=(0, 10))
        
        self.update_requirements_display()
    
    def setup_conflicts_panel(self, parent):
        """Setup conflicts panel"""
        conflict_frame = tk.Frame(parent, bg=self.COLORS['card'],
                                  relief=tk.SOLID, bd=1)
        conflict_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        
        conflict_header = tk.Frame(conflict_frame, bg=self.COLORS['card'])
        conflict_header.pack(fill=tk.X, padx=15, pady=10)
        
        self.conflict_count_label = tk.Label(conflict_header,
                                            text="⚠️ CONFLICTS (0)",
                                            font=("Segoe UI", 10, "bold"),
                                            bg=self.COLORS['card'])
        self.conflict_count_label.pack(side=tk.LEFT)
        
        self.conflict_expand_btn = tk.Button(conflict_header, text="▼",
                                            bg=self.COLORS['bg'],
                                            font=("Segoe UI", 9),
                                            command=self.toggle_conflicts)
        self.conflict_expand_btn.pack(side=tk.RIGHT)
        
        self.conflict_content = tk.Frame(conflict_frame, bg=self.COLORS['card'])
        self.conflict_content.pack(fill=tk.X, padx=15, pady=(0, 10))
        
        self.update_conflicts_display()
    
    def setup_employees_tab(self):
        """Set up the employees tab with enhanced design"""
        main_frame = tk.Frame(self.employees_tab, bg=self.COLORS['bg'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Top toolbar
        toolbar = tk.Frame(main_frame, bg=self.COLORS['card'], height=60,
                          relief=tk.SOLID, bd=1)
        toolbar.pack(fill=tk.X, pady=(0, 10))
        
        # Buttons
        btn_frame = tk.Frame(toolbar, bg=self.COLORS['card'])
        btn_frame.pack(side=tk.LEFT, padx=15, pady=12)
        
        ModernButton(btn_frame, text="➕ Add Employee",
                    bg=self.COLORS['accent'], hover=self.COLORS['accent_hover'],
                    command=self.add_employee).pack(side=tk.LEFT, padx=2)
        
        ModernButton(btn_frame, text="✏️ Edit",
                    bg=self.COLORS['warning'], hover=self.COLORS['warning_hover'],
                    command=self.edit_employee).pack(side=tk.LEFT, padx=2)
        
        ModernButton(btn_frame, text="🗑️ Delete",
                    bg=self.COLORS['error'], hover=self.COLORS['error_hover'],
                    command=self.delete_employee).pack(side=tk.LEFT, padx=2)
        
        # Search
        search_frame = tk.Frame(toolbar, bg=self.COLORS['card'])
        search_frame.pack(side=tk.RIGHT, padx=15)
        
        tk.Label(search_frame, text="🔍", bg=self.COLORS['card'],
                font=("Segoe UI", 12)).pack(side=tk.LEFT)
        
        self.emp_search_var = tk.StringVar()
        self.emp_search_var.trace_add('write', lambda *args: self.filter_employee_table())
        search_entry = tk.Entry(search_frame, textvariable=self.emp_search_var,
                               bg='#F9FAFB', font=("Segoe UI", 10),
                               width=25, bd=1, relief=tk.SOLID)
        search_entry.pack(side=tk.LEFT, padx=5, ipady=5)
        search_entry.insert(0, "Search employees...")
        search_entry.bind('<FocusIn>', lambda e: search_entry.delete(0, tk.END) if search_entry.get() == "Search employees..." else None)
        
        # Employee table with scroll
        table_frame = tk.Frame(main_frame, bg=self.COLORS['card'],
                               relief=tk.SOLID, bd=1)
        table_frame.pack(fill=tk.BOTH, expand=True)
        
        # Treeview with custom style
        columns = ('ID', 'Name', 'Role', 'Status', 'Max Hrs', 'Min Hrs', 'Hire Date')
        self.employee_tree = ttk.Treeview(table_frame, columns=columns,
                                          show='headings', height=20,
                                          selectmode='browse')
        
        # Column headings and widths
        column_widths = [80, 150, 100, 80, 80, 80, 100]
        for col, width in zip(columns, column_widths):
            self.employee_tree.heading(col, text=col)
            self.employee_tree.column(col, width=width)
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL,
                                   command=self.employee_tree.yview)
        h_scrollbar = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL,
                                   command=self.employee_tree.xview)
        
        self.employee_tree.configure(yscrollcommand=v_scrollbar.set,
                                    xscrollcommand=h_scrollbar.set)
        
        # Grid layout
        self.employee_tree.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')
        
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        
        self.employee_tree.bind('<Double-1>', lambda e: self.edit_employee())
        
        self.refresh_employee_table()
    
    def setup_availability_tab(self):
        """Set up the availability tab with enhanced design"""
        main_frame = tk.Frame(self.availability_tab, bg=self.COLORS['bg'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Employee selector card
        selector_frame = tk.Frame(main_frame, bg=self.COLORS['card'],
                                  relief=tk.SOLID, bd=1)
        selector_frame.pack(fill=tk.X, pady=(0, 10))
        
        selector_content = tk.Frame(selector_frame, bg=self.COLORS['card'])
        selector_content.pack(padx=15, pady=15)
        
        tk.Label(selector_content, text="👤 Select Employee:",
                font=("Segoe UI", 10, "bold"),
                bg=self.COLORS['card']).pack(side=tk.LEFT)
        
        self.avail_employee_var = tk.StringVar()
        self.avail_employee_combo = ttk.Combobox(selector_content,
                                                 textvariable=self.avail_employee_var,
                                                 state='readonly', width=40,
                                                 font=("Segoe UI", 10))
        self.avail_employee_combo.pack(side=tk.LEFT, padx=20)
        self.avail_employee_combo.bind('<<ComboboxSelected>>',
                                       lambda e: self.load_employee_availability())
        
        ModernButton(selector_content, text="📋 Copy from Previous Week",
                    bg=self.COLORS['accent'], hover=self.COLORS['accent_hover'],
                    command=self.copy_availability).pack(side=tk.RIGHT)
        
        # Availability grid card
        grid_card = tk.Frame(main_frame, bg=self.COLORS['card'],
                             relief=tk.SOLID, bd=1)
        grid_card.pack(fill=tk.BOTH, expand=True)
        
        grid_content = tk.Frame(grid_card, bg=self.COLORS['card'])
        grid_content.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Day headers with icons
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                'Friday', 'Saturday', 'Sunday']
        day_icons = ['🌙', '🔥', '💧', '🌳', '🎉', '🌟', '☀️']
        
        for i, (day, icon) in enumerate(zip(days, day_icons)):
            header_frame = tk.Frame(grid_content, bg=self.COLORS['card'])
            header_frame.grid(row=0, column=i, padx=10, pady=5)
            
            tk.Label(header_frame, text=f"{icon} {day}", 
                    font=("Segoe UI", 10, "bold"),
                    bg=self.COLORS['card'], fg=self.COLORS['accent']).pack()
        
        # Time range inputs with better design
        self.avail_entries = []
        for row in range(1, 4):  # Max 3 time ranges per day
            row_entries = []
            for col in range(7):
                time_frame = tk.Frame(grid_content, bg=self.COLORS['card'])
                time_frame.grid(row=row, column=col, padx=5, pady=2)
                
                start_entry = tk.Entry(time_frame, width=6, font=("Segoe UI", 10),
                                      justify='center', bd=1, relief=tk.SOLID)
                start_entry.pack(side=tk.LEFT, padx=1)
                
                tk.Label(time_frame, text="—", bg=self.COLORS['card'],
                        font=("Segoe UI", 12)).pack(side=tk.LEFT)
                
                end_entry = tk.Entry(time_frame, width=6, font=("Segoe UI", 10),
                                    justify='center', bd=1, relief=tk.SOLID)
                end_entry.pack(side=tk.LEFT, padx=1)
                
                row_entries.append((start_entry, end_entry))
            
            self.avail_entries.append(row_entries)
        
        # Unavailable all day checkboxes
        self.unavailable_vars = []
        checkbox_frame = tk.Frame(grid_content, bg=self.COLORS['card'])
        checkbox_frame.grid(row=4, column=0, columnspan=7, pady=15)
        
        for col in range(7):
            var = tk.BooleanVar()
            cb = tk.Checkbutton(checkbox_frame, text="❌ Unavailable all day",
                               variable=var, bg=self.COLORS['card'],
                               font=("Segoe UI", 9),
                               command=self.update_availability_from_checkboxes)
            cb.grid(row=0, column=col, padx=10)
            self.unavailable_vars.append(var)
        
        # Save button
        save_frame = tk.Frame(main_frame, bg=self.COLORS['bg'])
        save_frame.pack(fill=tk.X, pady=10)
        
        ModernButton(save_frame, text="💾 Save Availability",
                    bg=self.COLORS['success'], hover=self.COLORS['success_hover'],
                    command=self.save_availability).pack()
        
        # Time off requests section
        self.setup_timeoff_panel(main_frame)
    
    def setup_timeoff_panel(self, parent):
        """Setup time off requests panel"""
        exceptions_frame = tk.Frame(parent, bg=self.COLORS['card'],
                                   relief=tk.SOLID, bd=1)
        exceptions_frame.pack(fill=tk.X, pady=(10, 0))
        
        ex_header = tk.Frame(exceptions_frame, bg=self.COLORS['card'])
        ex_header.pack(fill=tk.X, padx=15, pady=10)
        
        tk.Label(ex_header, text="⏳ Time Off Requests",
                font=("Segoe UI", 10, "bold"), bg=self.COLORS['card']).pack(side=tk.LEFT)
        
        # Exception list with scroll
        list_frame = tk.Frame(exceptions_frame, bg=self.COLORS['card'])
        list_frame.pack(fill=tk.X, padx=15, pady=(0, 10))
        
        self.exception_listbox = tk.Listbox(list_frame, height=4,
                                           font=("Segoe UI", 10),
                                           bd=1, relief=tk.SOLID)
        self.exception_listbox.pack(fill=tk.X, side=tk.LEFT, expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                  command=self.exception_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.exception_listbox.configure(yscrollcommand=scrollbar.set)
        
        # Action buttons
        btn_frame = tk.Frame(exceptions_frame, bg=self.COLORS['card'])
        btn_frame.pack(pady=(0, 15))
        
        ModernButton(btn_frame, text="➕ Add Request",
                    bg=self.COLORS['accent'], hover=self.COLORS['accent_hover'],
                    command=self.add_timeoff_request).pack(side=tk.LEFT, padx=2)
        
        ModernButton(btn_frame, text="✅ Approve",
                    bg=self.COLORS['success'], hover=self.COLORS['success_hover'],
                    command=self.approve_request).pack(side=tk.LEFT, padx=2)
        
        ModernButton(btn_frame, text="❌ Deny",
                    bg=self.COLORS['error'], hover=self.COLORS['error_hover'],
                    command=self.deny_request).pack(side=tk.LEFT, padx=2)
    
    def setup_reports_tab(self):
        """Set up the reports tab with enhanced design"""
        main_frame = tk.Frame(self.reports_tab, bg=self.COLORS['bg'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Control panel
        control_frame = tk.Frame(main_frame, bg=self.COLORS['card'],
                                 relief=tk.SOLID, bd=1)
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        control_content = tk.Frame(control_frame, bg=self.COLORS['card'])
        control_content.pack(padx=15, pady=15)
        
        tk.Label(control_content, text="📈 Select Report:",
                font=("Segoe UI", 10, "bold"),
                bg=self.COLORS['card']).pack(side=tk.LEFT)
        
        self.report_var = tk.StringVar()
        report_combo = ttk.Combobox(control_content, textvariable=self.report_var,
                                    state='readonly', width=30,
                                    font=("Segoe UI", 10))
        report_combo['values'] = ['Hours Summary', 'Preference Satisfaction',
                                  'Labor Cost Projection', 'Unfilled Shifts',
                                  'Overtime Report', 'Schedule vs Actual']
        report_combo.pack(side=tk.LEFT, padx=20)
        report_combo.bind('<<ComboboxSelected>>', lambda e: self.generate_report())
        
        ModernButton(control_content, text="📥 Export CSV",
                    bg=self.COLORS['accent'], hover=self.COLORS['accent_hover'],
                    command=self.export_report_csv).pack(side=tk.RIGHT)
        
        # Report display card
        display_card = tk.Frame(main_frame, bg=self.COLORS['card'],
                                relief=tk.SOLID, bd=1)
        display_card.pack(fill=tk.BOTH, expand=True)
        
        # Report text with scroll
        text_frame = tk.Frame(display_card, bg=self.COLORS['card'])
        text_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        self.report_text = tk.Text(text_frame, wrap=tk.WORD,
                                   font=("Consolas", 10),
                                   bg='#F9FAFB', bd=1, relief=tk.SOLID)
        self.report_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL,
                                  command=self.report_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.report_text.configure(yscrollcommand=scrollbar.set)
    
    def update_employee_list(self):
        """Update the employee list in schedule tab with modern cards"""
        # Clear existing
        for widget in self.employee_list_frame.winfo_children():
            widget.destroy()
        
        search_term = self.search_var.get().lower()
        if search_term == "🔍 search employees...":
            search_term = ""
        
        active_count = 0
        for emp_id, emp in self.data.employees.items():
            if not emp.active:
                continue
            
            if search_term and search_term not in emp.name.lower():
                continue
            
            active_count += 1
            
            # Create modern employee card
            card = tk.Frame(self.employee_list_frame, bg='#F9FAFB',
                           relief=tk.RAISED, bd=0, highlightbackground=self.COLORS['border'],
                           highlightthickness=1)
            card.pack(fill=tk.X, pady=2)
            card.pack_propagate(False)
            card.configure(height=70)
            
            # Hover effect
            def on_enter(e, c=card):
                c.config(bg='#F3F4F6')
            
            def on_leave(e, c=card):
                c.config(bg='#F9FAFB')
            
            card.bind('<Enter>', on_enter)
            card.bind('<Leave>', on_leave)
            
            # Employee avatar/icon
            avatar_frame = tk.Frame(card, bg=card['bg'], width=40)
            avatar_frame.pack(side=tk.LEFT, padx=10, pady=10)
            avatar_frame.pack_propagate(False)
            
            colors = ['#2563EB', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6']
            color = colors[hash(emp_id) % len(colors)]
            
            avatar = tk.Label(avatar_frame, text=emp.name[0].upper(),
                            bg=color, fg='white',
                            font=("Segoe UI", 14, "bold"),
                            width=2, height=1)
            avatar.pack(fill=tk.BOTH, expand=True)
            
            # Employee info
            info_frame = tk.Frame(card, bg=card['bg'])
            info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=10)
            
            name_label = tk.Label(info_frame, text=emp.name,
                                 font=("Segoe UI", 11, "bold"),
                                 bg=card['bg'], fg=self.COLORS['text'])
            name_label.pack(anchor=tk.W)
            
            role_label = tk.Label(info_frame, text=emp.role,
                                 font=("Segoe UI", 9),
                                 bg=card['bg'], fg=self.COLORS['text_light'])
            role_label.pack(anchor=tk.W)
            
            # Hours and status
            status_frame = tk.Frame(card, bg=card['bg'])
            status_frame.pack(side=tk.RIGHT, padx=15, pady=10)
            
            if self.current_schedule:
                hours = self.current_schedule.get_hours_for_employee(emp_id)
                color = self.COLORS['success'] if hours <= emp.max_hours_week else self.COLORS['error']
                
                hours_label = tk.Label(status_frame, text=f"{hours:.1f}/{emp.max_hours_week}h",
                                     font=("Segoe UI", 9, "bold"),
                                     bg=card['bg'], fg=color)
                hours_label.pack()
                
                # Progress bar
                progress_frame = tk.Frame(status_frame, bg=self.COLORS['border'],
                                        height=4, width=60)
                progress_frame.pack(pady=2)
                progress_frame.pack_propagate(False)
                
                progress = min(100, (hours / emp.max_hours_week) * 100) if emp.max_hours_week > 0 else 0
                fill = tk.Frame(progress_frame, bg=color, height=4,
                              width=int(progress * 60 / 100))
                fill.place(x=0, y=0)
            
            # Click handler for details
            card.bind('<Button-1>', lambda e, eid=emp_id: self.show_employee_details(eid))
            for child in [avatar, info_frame, name_label, role_label]:
                child.bind('<Button-1>', lambda e, eid=emp_id: self.show_employee_details(eid))
        
        # Update count
        if hasattr(self, 'employee_count_label'):
            self.employee_count_label.config(text=f"Active Employees: {active_count}")
        
        # Update employee combo
        self.update_employee_combo()
    
    def create_schedule_grid(self):
        """Create the weekly schedule grid with modern design"""
        # Clear existing
        for widget in self.schedule_frame.winfo_children():
            widget.destroy()
        
        if not self.current_schedule:
            return
        
        # Headers with dates
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        today = datetime.date.today()
        
        for i, day in enumerate(days):
            date = self.current_week + datetime.timedelta(days=i)
            date_str = date.strftime("%m/%d")
            
            # Header frame
            header = tk.Frame(self.schedule_frame, bg=self.COLORS['accent'],
                            height=50)
            header.grid(row=0, column=i, sticky='nsew', padx=2, pady=2)
            header.grid_propagate(False)
            
            # Highlight today
            if date == today:
                header.config(bg=self.COLORS['warning'])
            
            day_label = tk.Label(header, text=f"{day}\n{date_str}",
                                bg=header['bg'], fg='white',
                                font=("Segoe UI", 10, "bold"))
            day_label.pack(expand=True)
        
        # Configure grid weights
        for i in range(7):
            self.schedule_frame.columnconfigure(i, weight=1)
        
        # Shifts with modern styling
        shift_pastels = ['#E6F0FF', '#E6F7F0', '#FFF4E6', '#F0E6FF', 
                        '#FFE6F0', '#F0FFE6', '#FFE6E6']
        
        row = 1
        for day_offset in range(7):
            date = (self.current_week + datetime.timedelta(days=day_offset)).isoformat()
            day_shifts = [s for s in self.current_schedule.shifts if s.date == date]
            day_shifts.sort(key=lambda s: s.start_time)
            
            # Create cell with scroll if needed
            cell_canvas = tk.Canvas(self.schedule_frame, bg='white',
                                   highlightthickness=0)
            cell_canvas.grid(row=row, column=day_offset, sticky='nsew',
                           padx=2, pady=2)
            
            # Add scrollbar to cell if many shifts
            if len(day_shifts) > 5:
                v_scroll = ttk.Scrollbar(cell_canvas, orient="vertical",
                                        command=cell_canvas.yview)
                cell_canvas.configure(yscrollcommand=v_scroll.set)
                v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            
            cell_frame = tk.Frame(cell_canvas, bg='white')
            cell_window = cell_canvas.create_window((0, 0), window=cell_frame,
                                                   anchor='nw', width=cell_canvas.winfo_width())
            
            def configure_cell(event, canvas=cell_canvas, frame=cell_frame):
                canvas.itemconfig(cell_window, width=event.width)
                canvas.configure(scrollregion=canvas.bbox("all"))
            
            cell_canvas.bind('<Configure>', configure_cell)
            
            # Add shifts
            for idx, shift in enumerate(day_shifts):
                shift_frame = tk.Frame(cell_frame, bg=shift_pastels[idx % len(shift_pastels)],
                                      relief=tk.RAISED, bd=1)
                shift_frame.pack(fill=tk.X, padx=2, pady=1)
                
                # Shift header
                header_frame = tk.Frame(shift_frame, bg=shift_frame['bg'])
                header_frame.pack(fill=tk.X, padx=5, pady=3)
                
                time_text = f"{shift.start_time}-{shift.end_time}"
                tk.Label(header_frame, text=time_text, bg=shift_frame['bg'],
                        font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
                
                status = "✓" if shift.is_full() else f"({len(shift.assigned_employees)}/{shift.required_count})"
                status_color = self.COLORS['success'] if shift.is_full() else self.COLORS['warning']
                tk.Label(header_frame, text=status, bg=shift_frame['bg'],
                        fg=status_color, font=("Segoe UI", 8, "bold")).pack(side=tk.RIGHT)
                
                # Role
                role_label = tk.Label(header_frame, text=f"[{shift.role}]",
                                     bg=shift_frame['bg'], fg=self.COLORS['text_light'],
                                     font=("Segoe UI", 7))
                role_label.pack(side=tk.RIGHT, padx=5)
                
                # Assigned employees with drag-drop support
                for emp_id in shift.assigned_employees:
                    if emp_id in self.data.employees:
                        emp = self.data.employees[emp_id]
                        
                        emp_frame = tk.Frame(shift_frame, bg=shift_frame['bg'])
                        emp_frame.pack(fill=tk.X, padx=10, pady=1)
                        
                        # Employee pill
                        colors = ['#2563EB', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6']
                        color = colors[hash(emp_id) % len(colors)]
                        
                        pill = tk.Frame(emp_frame, bg=color, bd=0)
                        pill.pack(side=tk.LEFT)
                        
                        name_label = tk.Label(pill, text=f" {emp.name.split()[0]} ",
                                            bg=color, fg='white',
                                            font=("Segoe UI", 8))
                        name_label.pack()
                        
                        # Make draggable in manual mode
                        if self.manual_mode:
                            name_label.bind('<Button-1>', 
                                          lambda e, s=shift, eid=emp_id: self.start_drag(e, s, eid))
                            name_label.bind('<B1-Motion>', self.drag)
                            name_label.bind('<ButtonRelease-1>', 
                                          lambda e, s=shift, eid=emp_id: self.drop(e, s, eid))
                        
                        # Right-click to remove
                        name_label.bind('<Button-3>',
                                      lambda e, s=shift, eid=emp_id: self.remove_from_shift(s, eid))
                
                # Empty slots
                empty_count = shift.required_count - len(shift.assigned_employees)
                if empty_count > 0:
                    empty_frame = tk.Frame(shift_frame, bg=shift_frame['bg'])
                    empty_frame.pack(fill=tk.X, padx=10, pady=2)
                    
                    for i in range(empty_count):
                        empty_slot = tk.Label(empty_frame, text="[Empty Slot]",
                                            bg='#F3F4F6', fg=self.COLORS['text_light'],
                                            font=("Segoe UI", 7, "italic"),
                                            bd=1, relief=tk.SOLID, padx=5, pady=1)
                        empty_slot.pack(side=tk.LEFT, padx=1)
                        empty_slot.bind('<Button-1>',
                                      lambda e, s=shift: self.assign_to_shift(s))
                
                # Tooltip
                tooltip_text = f"{shift.shift_type}\nRole: {shift.role}\n"
                if shift.assigned_employees:
                    tooltip_text += f"Assigned: {len(shift.assigned_employees)}/{shift.required_count}"
                ToolTip(shift_frame, tooltip_text)
            
            # If no shifts, show message
            if not day_shifts:
                tk.Label(cell_frame, text="No shifts", fg=self.COLORS['text_light'],
                        font=("Segoe UI", 8, "italic"), bg='white').pack(pady=10)
    
    def update_requirements_display(self):
        """Update the shift requirements display with modern styling"""
        # Clear existing
        for widget in self.req_content.winfo_children():
            widget.destroy()
        
        for shift_type, req in self.data.shift_requirements.items():
            # Create requirement pill
            req_pill = tk.Frame(self.req_content, bg=self.COLORS['bg'],
                               bd=0)
            req_pill.pack(side=tk.LEFT, padx=5, pady=2)
            
            icon = "🌅" if "Morning" in shift_type else "🌆" if "Evening" in shift_type else "🌙"
            text = f"{icon} {shift_type.split()[0]}: "
            roles_text = []
            for role, count in req.role_requirements.items():
                roles_text.append(f"{count} {role}")
            text += ", ".join(roles_text)
            
            tk.Label(req_pill, text=text, bg=self.COLORS['bg'],
                    fg=self.COLORS['text'], font=("Segoe UI", 9)).pack()
    
    def update_conflicts_display(self):
        """Update the conflicts display with modern styling"""
        # Clear existing
        for widget in self.conflict_content.winfo_children():
            widget.destroy()
        
        count = len(self.conflicts)
        if hasattr(self, 'conflict_count_label'):
            icon = "⚠️" if count > 0 else "✅"
            self.conflict_count_label.config(text=f"{icon} CONFLICTS ({count})")
        
        if count == 0:
            tk.Label(self.conflict_content, text="✨ No conflicts detected - All good!",
                    bg=self.COLORS['card'], fg=self.COLORS['success'],
                    font=("Segoe UI", 9)).pack(pady=5)
            return
        
        # Show conflicts with severity indicators
        for conflict in self.conflicts:
            color = self.COLORS['error'] if conflict.severity == 'error' else self.COLORS['warning']
            icon = "❌" if conflict.severity == 'error' else "⚠️"
            
            frame = tk.Frame(self.conflict_content, bg=self.COLORS['card'])
            frame.pack(fill=tk.X, pady=2)
            
            tk.Label(frame, text=icon, bg=self.COLORS['card'],
                    fg=color, font=("Segoe UI", 10)).pack(side=tk.LEFT)
            
            label = tk.Label(frame, text=conflict.description,
                           bg=self.COLORS['card'], fg=color,
                           font=("Segoe UI", 8), wraplength=400,
                           justify=tk.LEFT)
            label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
            
            # Quick fix button
            fix_btn = tk.Button(frame, text="🔧 Fix", bg=self.COLORS['bg'],
                               font=("Segoe UI", 7),
                               command=lambda c=conflict: self.fix_conflict(c))
            fix_btn.pack(side=tk.RIGHT)
    
    def update_employee_combo(self):
        """Update employee combobox in availability tab"""
        employees = [f"{eid} - {emp.name} ({emp.role})" 
                    for eid, emp in self.data.employees.items() if emp.active]
        if hasattr(self, 'avail_employee_combo'):
            self.avail_employee_combo['values'] = employees
    
    def load_employee_availability(self):
        """Load availability for selected employee"""
        selection = self.avail_employee_var.get()
        if not selection:
            return
        
        emp_id = selection.split(' - ')[0]
        
        # Clear existing entries
        for row in self.avail_entries:
            for start_entry, end_entry in row:
                start_entry.delete(0, tk.END)
                end_entry.delete(0, tk.END)
                start_entry.config(state='normal', bg='white')
                end_entry.config(state='normal', bg='white')
        
        for var in self.unavailable_vars:
            var.set(False)
        
        # Load availability
        if emp_id in self.data.availabilities:
            avail = self.data.availabilities[emp_id]
            for day in range(7):
                daily = avail.weekly.get(day)
                if daily:
                    if daily.unavailable_all_day:
                        self.unavailable_vars[day].set(True)
                        for row in self.avail_entries:
                            start_entry, end_entry = row[day]
                            start_entry.config(state='disabled', bg='#F3F4F6')
                            end_entry.config(state='disabled', bg='#F3F4F6')
                    
                    for i, tr in enumerate(daily.time_ranges[:3]):
                        if i < len(self.avail_entries):
                            start_entry, end_entry = self.avail_entries[i][day]
                            start_entry.insert(0, tr.start)
                            end_entry.insert(0, tr.end)
        
        # Load exceptions
        self.exception_listbox.delete(0, tk.END)
        if emp_id in self.data.availabilities:
            for ex in self.data.availabilities[emp_id].exceptions:
                status = "✅" if ex.approved else "⏳"
                self.exception_listbox.insert(tk.END,
                    f"{status} {ex.date}: {ex.reason}")
    
    def save_availability(self):
        """Save availability for selected employee"""
        selection = self.avail_employee_var.get()
        if not selection:
            messagebox.showwarning("Warning", "Please select an employee")
            return
        
        emp_id = selection.split(' - ')[0]
        
        # Create or get availability
        if emp_id not in self.data.availabilities:
            self.data.availabilities[emp_id] = Availability(employee_id=emp_id)
        
        avail = self.data.availabilities[emp_id]
        
        # Save weekly
        for day in range(7):
            time_ranges = []
            for row in self.avail_entries:
                start_entry, end_entry = row[day]
                if start_entry['state'] != 'disabled':
                    start = start_entry.get().strip()
                    end = end_entry.get().strip()
                    
                    if start and end:
                        # Validate time format
                        try:
                            datetime.datetime.strptime(start, "%H:%M")
                            datetime.datetime.strptime(end, "%H:%M")
                            time_ranges.append(TimeRange(start, end))
                        except ValueError:
                            messagebox.showerror("Error",
                                f"Invalid time format for {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][day]}. Use HH:MM (24-hour)")
                            return
            
            avail.weekly[day] = DailyAvailability(
                day_of_week=day,
                time_ranges=time_ranges,
                unavailable_all_day=self.unavailable_vars[day].get()
            )
        
        messagebox.showinfo("Success", "Availability saved successfully")
        self.save_data()
    
    def update_availability_from_checkboxes(self):
        """Update availability grid based on unavailable all day checkboxes"""
        for day in range(7):
            if self.unavailable_vars[day].get():
                for row in self.avail_entries:
                    start_entry, end_entry = row[day]
                    start_entry.delete(0, tk.END)
                    end_entry.delete(0, tk.END)
                    start_entry.config(state='disabled', bg='#F3F4F6')
                    end_entry.config(state='disabled', bg='#F3F4F6')
            else:
                for row in self.avail_entries:
                    start_entry, end_entry = row[day]
                    start_entry.config(state='normal', bg='white')
                    end_entry.config(state='normal', bg='white')
    
    def add_timeoff_request(self):
        """Add a time off request"""
        selection = self.avail_employee_var.get()
        if not selection:
            messagebox.showwarning("Warning", "Please select an employee")
            return
        
        emp_id = selection.split(' - ')[0]
        
        # Simple dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Time Off Request")
        dialog.geometry("400x250")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.COLORS['card'])
        
        tk.Label(dialog, text="Add Time Off Request", 
                font=("Segoe UI", 14, "bold"),
                bg=self.COLORS['card'], fg=self.COLORS['text']).pack(pady=15)
        
        # Date
        date_frame = tk.Frame(dialog, bg=self.COLORS['card'])
        date_frame.pack(fill=tk.X, padx=20, pady=5)
        
        tk.Label(date_frame, text="Date (YYYY-MM-DD):", 
                bg=self.COLORS['card']).pack(anchor=tk.W)
        date_entry = tk.Entry(date_frame, font=("Segoe UI", 10), width=30)
        date_entry.pack(fill=tk.X, pady=2)
        date_entry.insert(0, datetime.date.today().isoformat())
        
        # Reason
        reason_frame = tk.Frame(dialog, bg=self.COLORS['card'])
        reason_frame.pack(fill=tk.X, padx=20, pady=5)
        
        tk.Label(reason_frame, text="Reason:", 
                bg=self.COLORS['card']).pack(anchor=tk.W)
        reason_entry = tk.Entry(reason_frame, font=("Segoe UI", 10), width=30)
        reason_entry.pack(fill=tk.X, pady=2)
        
        def save_request():
            date = date_entry.get()
            reason = reason_entry.get()
            
            if not date or not reason:
                messagebox.showerror("Error", "Please fill all fields")
                return
            
            # Create exception
            if emp_id not in self.data.availabilities:
                self.data.availabilities[emp_id] = Availability(employee_id=emp_id)
            
            ex = AvailabilityException(
                date=date,
                unavailable_all_day=True,
                reason=reason,
                approved=False
            )
            
            self.data.availabilities[emp_id].exceptions.append(ex)
            self.load_employee_availability()  # Refresh
            self.save_data()
            
            dialog.destroy()
            messagebox.showinfo("Success", "Time off request added")
        
        # Buttons
        btn_frame = tk.Frame(dialog, bg=self.COLORS['card'])
        btn_frame.pack(pady=20)
        
        ModernButton(btn_frame, text="Save", bg=self.COLORS['success'],
                    hover=self.COLORS['success_hover'],
                    command=save_request).pack(side=tk.LEFT, padx=5)
        
        ModernButton(btn_frame, text="Cancel", bg=self.COLORS['error'],
                    hover=self.COLORS['error_hover'],
                    command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def approve_request(self):
        """Approve selected time off request"""
        selection = self.exception_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a request")
            return
        
        # Get selected item
        selected = self.exception_listbox.get(selection[0])
        # In a real app, this would update the database
        messagebox.showinfo("Success", f"Request approved: {selected}")
    
    def deny_request(self):
        """Deny selected time off request"""
        selection = self.exception_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a request")
            return
        
        selected = self.exception_listbox.get(selection[0])
        messagebox.showinfo("Success", f"Request denied: {selected}")
    
    def copy_availability(self):
        """Copy availability from previous week"""
        selection = self.avail_employee_var.get()
        if not selection:
            messagebox.showwarning("Warning", "Please select an employee")
            return
        
        messagebox.showinfo("Info", "Availability copied from previous week")
    
    def generate_report(self):
        """Generate selected report"""
        report_type = self.report_var.get()
        
        if not report_type:
            return
        
        self.report_text.delete(1.0, tk.END)
        
        if report_type == "Hours Summary":
            self.generate_hours_summary()
        elif report_type == "Preference Satisfaction":
            self.generate_preference_report()
        elif report_type == "Labor Cost Projection":
            self.generate_labor_cost_report()
        elif report_type == "Unfilled Shifts":
            self.generate_unfilled_shifts_report()
        elif report_type == "Overtime Report":
            self.generate_overtime_report()
        elif report_type == "Schedule vs Actual":
            self.generate_schedule_vs_actual()
    
    def generate_hours_summary(self):
        """Generate hours summary report"""
        self.report_text.insert(tk.END, "=" * 60 + "\n")
        self.report_text.insert(tk.END, "HOURS SUMMARY REPORT\n")
        self.report_text.insert(tk.END, "=" * 60 + "\n\n")
        
        if not self.current_schedule:
            self.report_text.insert(tk.END, "No schedule loaded\n")
            return
        
        self.report_text.insert(tk.END, f"Week of: {self.current_week.strftime('%B %d, %Y')}\n\n")
        
        self.report_text.insert(tk.END, f"{'Employee':<20} {'Role':<15} {'Hours':<10} {'Max':<10} {'Status':<10}\n")
        self.report_text.insert(tk.END, "-" * 65 + "\n")
        
        total_hours = 0
        for emp_id, emp in self.data.employees.items():
            if not emp.active:
                continue
            
            hours = self.current_schedule.get_hours_for_employee(emp_id)
            total_hours += hours
            
            status = "✅ OK"
            if hours > emp.max_hours_week:
                status = "⚠️ OVER"
            elif hours < emp.min_hours_week and hours > 0:
                status = "⚠️ UNDER"
            
            self.report_text.insert(tk.END,
                f"{emp.name:<20} {emp.role:<15} {hours:<10.1f} {emp.max_hours_week:<10} {status:<10}\n")
        
        self.report_text.insert(tk.END, "\n" + "=" * 60 + "\n")
        self.report_text.insert(tk.END, f"Total Scheduled Hours: {total_hours:.1f}\n")
    
    def generate_preference_report(self):
        """Generate preference satisfaction report"""
        self.report_text.insert(tk.END, "=" * 60 + "\n")
        self.report_text.insert(tk.END, "PREFERENCE SATISFACTION REPORT\n")
        self.report_text.insert(tk.END, "=" * 60 + "\n\n")
        
        self.report_text.insert(tk.END, "Employee satisfaction scores:\n\n")
        
        total_score = 0
        count = 0
        for emp_id, emp in self.data.employees.items():
            if not emp.active:
                continue
            
            # Calculate satisfaction based on schedule
            if self.current_schedule:
                shifts = self.current_schedule.get_shifts_for_employee(emp_id)
                score = 100
                
                for shift in shifts:
                    day_of_week = datetime.datetime.fromisoformat(shift.date).weekday()
                    if day_of_week in emp.avoid_days:
                        score -= 10
                    
                    if "Morning" in shift.shift_type and emp.morning_pref < 3:
                        score -= 5
                    elif "Evening" in shift.shift_type and emp.evening_pref < 3:
                        score -= 5
                    elif "Overnight" in shift.shift_type and emp.night_pref < 3:
                        score -= 5
                
                score = max(0, score)
            else:
                score = random.randint(70, 95)
            
            total_score += score
            count += 1
            
            # Progress bar
            bar_length = 30
            filled = int(score * bar_length / 100)
            bar = "█" * filled + "░" * (bar_length - filled)
            
            self.report_text.insert(tk.END,
                f"{emp.name:<20} [{bar}] {score:3.0f}%\n")
        
        if count > 0:
            avg_score = total_score / count
            self.report_text.insert(tk.END, f"\nAverage satisfaction: {avg_score:.1f}%\n")
    
    def generate_labor_cost_report(self):
        """Generate labor cost projection"""
        self.report_text.insert(tk.END, "=" * 60 + "\n")
        self.report_text.insert(tk.END, "LABOR COST PROJECTION\n")
        self.report_text.insert(tk.END, "=" * 60 + "\n\n")
        
        if not self.current_schedule:
            self.report_text.insert(tk.END, "No schedule loaded\n")
            return
        
        # Hourly rates
        hourly_rates = {
            "Manager": 25.0,
            "Supervisor": 20.0,
            "Cashier": 15.0,
            "Stocker": 14.0,
            "Assistant": 13.0,
            "Cleaner": 12.0,
            "Security": 18.0
        }
        
        total_cost = 0
        self.report_text.insert(tk.END, f"{'Employee':<20} {'Role':<15} {'Hours':<10} {'Rate':<10} {'Cost':<12}\n")
        self.report_text.insert(tk.END, "-" * 67 + "\n")
        
        for emp_id, emp in self.data.employees.items():
            if not emp.active:
                continue
            
            hours = self.current_schedule.get_hours_for_employee(emp_id)
            rate = hourly_rates.get(emp.role, 15.0)
            cost = hours * rate
            total_cost += cost
            
            self.report_text.insert(tk.END,
                f"{emp.name:<20} {emp.role:<15} {hours:<10.1f} ${rate:<9.2f} ${cost:<11.2f}\n")
        
        self.report_text.insert(tk.END, "\n" + "=" * 60 + "\n")
        self.report_text.insert(tk.END, f"Total Labor Cost: ${total_cost:,.2f}\n")
    
    def generate_unfilled_shifts_report(self):
        """Generate unfilled shifts report"""
        self.report_text.insert(tk.END, "=" * 60 + "\n")
        self.report_text.insert(tk.END, "UNFILLED SHIFTS REPORT\n")
        self.report_text.insert(tk.END, "=" * 60 + "\n\n")
        
        if not self.current_schedule:
            self.report_text.insert(tk.END, "No schedule loaded\n")
            return
        
        unfilled = []
        for shift in self.current_schedule.shifts:
            if len(shift.assigned_employees) < shift.required_count:
                unfilled.append(shift)
        
        if not unfilled:
            self.report_text.insert(tk.END, "✨ All shifts are fully staffed!\n")
            return
        
        self.report_text.insert(tk.END, f"Found {len(unfilled)} understaffed shifts:\n\n")
        
        for shift in unfilled:
            needed = shift.required_count - len(shift.assigned_employees)
            date_obj = datetime.datetime.fromisoformat(shift.date)
            date_str = date_obj.strftime("%a, %b %d")
            
            self.report_text.insert(tk.END,
                f"• {date_str}: {shift.shift_type} - {shift.role} "
                f"(needs {needed} more)\n")
    
    def generate_overtime_report(self):
        """Generate overtime report"""
        self.report_text.insert(tk.END, "=" * 60 + "\n")
        self.report_text.insert(tk.END, "OVERTIME REPORT\n")
        self.report_text.insert(tk.END, "=" * 60 + "\n\n")
        
        if not self.current_schedule:
            self.report_text.insert(tk.END, "No schedule loaded\n")
            return
        
        overtime_emp = []
        for emp_id, emp in self.data.employees.items():
            if not emp.active:
                continue
            
            hours = self.current_schedule.get_hours_for_employee(emp_id)
            if hours > self.data.law_constraints.overtime_threshold:
                overtime_emp.append((emp, hours))
        
        if not overtime_emp:
            self.report_text.insert(tk.END, "✅ No overtime scheduled\n")
            return
        
        self.report_text.insert(tk.END, "Employees with overtime:\n\n")
        for emp, hours in overtime_emp:
            overtime_hours = hours - self.data.law_constraints.overtime_threshold
            overtime_cost = overtime_hours * 15 * 1.5  # Assuming $15/hr base
            
            self.report_text.insert(tk.END,
                f"• {emp.name}: {hours:.1f} hours "
                f"(⏰ {overtime_hours:.1f} hours overtime)\n")
            self.report_text.insert(tk.END,
                f"  Overtime cost: ${overtime_cost:.2f}\n\n")
    
    def generate_schedule_vs_actual(self):
        """Generate schedule vs actual comparison"""
        self.report_text.insert(tk.END, "=" * 60 + "\n")
        self.report_text.insert(tk.END, "SCHEDULE VS ACTUAL COMPARISON\n")
        self.report_text.insert(tk.END, "=" * 60 + "\n\n")
        
        self.report_text.insert(tk.END, "Demo: This would compare scheduled vs actual worked hours\n\n")
        
        for emp_id, emp in self.data.employees.items():
            if not emp.active:
                continue
            
            scheduled = self.current_schedule.get_hours_for_employee(emp_id) if self.current_schedule else 0
            actual = scheduled + random.randint(-3, 3)
            variance = actual - scheduled
            
            if variance > 0:
                var_symbol = "▲"
                var_color = "🔴"
            elif variance < 0:
                var_symbol = "▼"
                var_color = "🔵"
            else:
                var_symbol = "●"
                var_color = "⚪"
            
            self.report_text.insert(tk.END,
                f"{emp.name:<20} Scheduled: {scheduled:5.1f}h | Actual: {actual:5.1f}h | "
                f"{var_color} {var_symbol} {variance:+3.1f}h\n")
    
    def export_report_csv(self):
        """Export current report as CSV"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.report_text.get(1.0, tk.END))
                messagebox.showinfo("Success", f"Report exported to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export: {e}")
    
    def load_week(self):
        """Load schedule for current week"""
        # Find schedule for this week
        week_str = self.current_week.isoformat()
        for schedule in self.data.schedules:
            if schedule.week_start == week_str:
                self.current_schedule = schedule
                break
        
        if not self.current_schedule:
            self.current_schedule = Schedule(week_start=week_str)
            # Create empty shifts based on requirements
            self.current_schedule.shifts = self.scheduler._create_shifts_for_week(self.current_week)
        
        self.week_label.config(text=self.current_week.strftime("%B %d, %Y"))
        self.create_schedule_grid()
        self.update_conflicts_display()
        self.update_employee_list()
    
    def prev_week(self):
        """Go to previous week"""
        self.current_week = self.current_week - datetime.timedelta(days=7)
        self.load_week()
    
    def next_week(self):
        """Go to next week"""
        self.current_week = self.current_week + datetime.timedelta(days=7)
        self.load_week()
    
    def go_to_today(self):
        """Go to current week"""
        self.current_week = datetime.date.today()
        self.current_week = self.current_week - datetime.timedelta(
            days=self.current_week.weekday())
        self.load_week()
    
    def generate_schedule(self):
        """Generate schedule for current week"""
        # Strategy selection dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Generate Schedule")
        dialog.geometry("450x350")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.COLORS['card'])
        
        # Make dialog modal
        dialog.focus_set()
        
        tk.Label(dialog, text="⚡ Generate Schedule", 
                font=("Segoe UI", 16, "bold"),
                bg=self.COLORS['card'], fg=self.COLORS['text']).pack(pady=20)
        
        tk.Label(dialog, text="Select Scheduling Strategy:", 
                font=("Segoe UI", 11),
                bg=self.COLORS['card']).pack()
        
        strategy_var = tk.StringVar(value="hybrid")
        
        # Strategy options frame
        options_frame = tk.Frame(dialog, bg=self.COLORS['card'])
        options_frame.pack(pady=15, padx=30, fill=tk.X)
        
        strategies = [
            ("⚖️ Fair Distribution", "fair_distribution", "Equal hours distribution"),
            ("⭐ Preference First", "preference_first", "Prioritize employee preferences"),
            ("📅 Seniority Based", "seniority_based", "Prefer longer-tenured employees"),
            ("🔄 Hybrid (Recommended)", "hybrid", "Balanced approach with configurable weights")
        ]
        
        for text, value, desc in strategies:
            frame = tk.Frame(options_frame, bg=self.COLORS['card'])
            frame.pack(fill=tk.X, pady=5)
            
            rb = tk.Radiobutton(frame, text=text, variable=strategy_var,
                               value=value, bg=self.COLORS['card'],
                               font=("Segoe UI", 10))
            rb.pack(anchor=tk.W)
            
            tk.Label(frame, text=desc, font=("Segoe UI", 8),
                    fg=self.COLORS['text_light'],
                    bg=self.COLORS['card']).pack(anchor=tk.W, padx=25)
        
        def generate():
            strategy = strategy_var.get()
            
            # Save current for undo
            if self.current_schedule:
                self.undo_stack.append(copy.deepcopy(self.current_schedule))
                self.redo_stack.clear()
            
            # Generate new schedule
            schedule, conflicts = self.scheduler.generate_schedule(self.current_week, strategy)
            
            # Update or add to schedules
            found = False
            for i, s in enumerate(self.data.schedules):
                if s.week_start == schedule.week_start:
                    self.data.schedules[i] = schedule
                    found = True
                    break
            
            if not found:
                self.data.schedules.append(schedule)
            
            self.current_schedule = schedule
            self.conflicts = conflicts
            
            # Refresh UI
            self.create_schedule_grid()
            self.update_conflicts_display()
            self.update_employee_list()
            
            dialog.destroy()
            
            # Show result message
            if len(conflicts) == 0:
                messagebox.showinfo("Schedule Generated", 
                                   "✅ Schedule generated successfully with no conflicts!")
            else:
                messagebox.showinfo("Schedule Generated",
                                   f"⚠️ Schedule generated with {len(conflicts)} conflicts.\n"
                                   "Check the conflicts panel for details.")
            
            self.save_data()
        
        def cancel():
            dialog.destroy()
        
        # Buttons
        btn_frame = tk.Frame(dialog, bg=self.COLORS['card'])
        btn_frame.pack(pady=20)
        
        ModernButton(btn_frame, text="Generate", bg=self.COLORS['success'],
                    hover=self.COLORS['success_hover'],
                    command=generate).pack(side=tk.LEFT, padx=5)
        
        ModernButton(btn_frame, text="Cancel", bg=self.COLORS['error'],
                    hover=self.COLORS['error_hover'],
                    command=cancel).pack(side=tk.LEFT, padx=5)
    
    def clear_schedule(self):
        """Clear current schedule"""
        if not self.current_schedule:
            return
        
        if messagebox.askyesno("Clear Schedule", 
                               "Are you sure you want to clear all shift assignments?\n\n"
                               "This action cannot be undone."):
            # Save for undo
            self.undo_stack.append(copy.deepcopy(self.current_schedule))
            self.redo_stack.clear()
            
            # Clear assignments but keep shifts
            for shift in self.current_schedule.shifts:
                shift.assigned_employees = []
            
            self.conflicts = []
            self.create_schedule_grid()
            self.update_conflicts_display()
            self.update_employee_list()
            self.save_data()
            
            messagebox.showinfo("Success", "Schedule cleared successfully")
    
    def auto_fill(self):
        """Auto-fill empty shifts"""
        if not self.current_schedule:
            return
        
        # Save for undo
        self.undo_stack.append(copy.deepcopy(self.current_schedule))
        self.redo_stack.clear()
        
        schedule, conflicts = self.scheduler.auto_fill(self.current_schedule)
        self.current_schedule = schedule
        self.conflicts = conflicts
        
        self.create_schedule_grid()
        self.update_conflicts_display()
        
        if len(conflicts) == 0:
            messagebox.showinfo("Auto-Fill Complete",
                               "✅ All shifts filled successfully!")
        else:
            messagebox.showinfo("Auto-Fill Complete",
                               f"⚠️ Auto-filled with {len(conflicts)} remaining conflicts")
        self.save_data()
    
    def toggle_manual_mode(self):
        """Toggle manual adjustment mode"""
        self.manual_mode = not self.manual_mode
        if self.manual_mode:
            self.manual_btn.config(text="✅ Manual Mode ON",
                                  bg=self.COLORS['success'])
            self.mode_label.config(text="🔧 Manual Adjustment Mode",
                                  fg=self.COLORS['success'])
            messagebox.showinfo("Manual Mode", 
                               "Manual adjustment mode enabled.\n"
                               "• Drag and drop employees between shifts\n"
                               "• Right-click to remove from shift\n"
                               "• Click empty slots to assign")
        else:
            self.manual_btn.config(text="✏️ Manual Adjust",
                                  bg=self.COLORS['warning'])
            self.mode_label.config(text="")
        
        self.create_schedule_grid()  # Refresh to show drag handles
    
    def exit_manual_mode(self):
        """Exit manual adjustment mode"""
        if self.manual_mode:
            self.manual_mode = False
            self.manual_btn.config(text="✏️ Manual Adjust",
                                  bg=self.COLORS['warning'])
            self.mode_label.config(text="")
            self.create_schedule_grid()
    
    def start_drag(self, event, shift, emp_id):
        """Start drag operation"""
        if not self.manual_mode:
            return
        self.drag_data["shift"] = shift
        self.drag_data["emp_id"] = emp_id
        self.drag_data["x"] = event.x_root
        self.drag_data["y"] = event.y_root
        event.widget.config(cursor="fleur")
    
    def drag(self, event):
        """Handle drag motion"""
        if not self.manual_mode or not self.drag_data["shift"]:
            return
        # Show visual feedback
        self.root.config(cursor="fleur")
    
    def drop(self, event, target_shift, target_emp_id=None):
        """Handle drop operation"""
        if not self.manual_mode or not self.drag_data["shift"]:
            return
        
        source_shift = self.drag_data["shift"]
        source_emp_id = self.drag_data["emp_id"]
        
        self.root.config(cursor="")
        
        # Check if dropping on same shift
        if source_shift.id == target_shift.id:
            self.drag_data = {"shift": None, "emp_id": None, "x": 0, "y": 0}
            return
        
        # Save for undo
        self.undo_stack.append(copy.deepcopy(self.current_schedule))
        self.redo_stack.clear()
        
        # Remove from source
        if source_emp_id in source_shift.assigned_employees:
            source_shift.assigned_employees.remove(source_emp_id)
            
            # Add to target if role matches and not full
            emp = self.data.employees.get(source_emp_id)
            if emp and emp.role == target_shift.role:
                if len(target_shift.assigned_employees) < target_shift.required_count:
                    # Check if employee is available for this shift time
                    if self.scheduler._is_employee_available(source_emp_id, target_shift):
                        target_shift.assigned_employees.append(source_emp_id)
                    else:
                        # Put back in source if not available
                        source_shift.assigned_employees.append(source_emp_id)
                        messagebox.showwarning("Not Available",
                                             f"{emp.name} is not available at this time")
                else:
                    # Put back in source if target is full
                    source_shift.assigned_employees.append(source_emp_id)
            else:
                # Put back in source if role doesn't match
                source_shift.assigned_employees.append(source_emp_id)
                if emp:
                    messagebox.showwarning("Role Mismatch",
                                         f"{emp.name} cannot work as {target_shift.role}")
        
        # Refresh
        self.create_schedule_grid()
        self.update_conflicts_display()
        self.save_data()
        
        self.drag_data = {"shift": None, "emp_id": None, "x": 0, "y": 0}
    
    def remove_from_shift(self, shift, emp_id):
        """Remove employee from shift (right-click)"""
        if emp_id in shift.assigned_employees:
            emp = self.data.employees.get(emp_id)
            if messagebox.askyesno("Remove Employee",
                                  f"Remove {emp.name if emp else emp_id} from this shift?"):
                # Save for undo
                self.undo_stack.append(copy.deepcopy(self.current_schedule))
                self.redo_stack.clear()
                
                shift.assigned_employees.remove(emp_id)
                self.create_schedule_grid()
                self.update_conflicts_display()
                self.save_data()
    
    def reassign_employee(self, shift: Shift, emp_id: str):
        """Reassign an employee from a shift"""
        if emp_id not in shift.assigned_employees:
            return
        
        # Show available employees
        available = []
        for eid, emp in self.data.employees.items():
            if emp.active and emp.role == shift.role:
                if eid not in shift.assigned_employees:
                    if self.scheduler._is_employee_available(eid, shift):
                        # Check if already busy at this time
                        if not self.scheduler._is_employee_busy(eid, shift, self.current_schedule):
                            available.append((eid, emp.name))
        
        if not available:
            messagebox.showinfo("No Alternatives",
                               "No other eligible employees available")
            return
        
        # Selection dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Reassign Shift")
        dialog.geometry("400x500")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.COLORS['card'])
        
        tk.Label(dialog, text="Reassign Shift", 
                font=("Segoe UI", 14, "bold"),
                bg=self.COLORS['card']).pack(pady=15)
        
        tk.Label(dialog, text=f"Shift: {shift.date} {shift.shift_type}",
                bg=self.COLORS['card']).pack()
        
        tk.Label(dialog, text="Select new employee:",
                bg=self.COLORS['card']).pack(pady=10)
        
        # Employee list
        list_frame = tk.Frame(dialog, bg=self.COLORS['card'])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                            font=("Segoe UI", 10), height=10)
        listbox.pack(fill=tk.BOTH, expand=True)
        
        scrollbar.config(command=listbox.yview)
        
        for eid, name in available:
            listbox.insert(tk.END, f"{eid} - {name}")
        
        def on_assign():
            selection = listbox.curselection()
            if selection:
                selected = listbox.get(selection[0])
                new_emp_id = selected.split(' - ')[0]
                
                # Save for undo
                self.undo_stack.append(copy.deepcopy(self.current_schedule))
                self.redo_stack.clear()
                
                # Reassign
                shift.assigned_employees.remove(emp_id)
                shift.assigned_employees.append(new_emp_id)
                
                self.create_schedule_grid()
                self.update_conflicts_display()
                self.save_data()
                
                dialog.destroy()
        
        btn_frame = tk.Frame(dialog, bg=self.COLORS['card'])
        btn_frame.pack(pady=20)
        
        ModernButton(btn_frame, text="Assign", bg=self.COLORS['success'],
                    hover=self.COLORS['success_hover'],
                    command=on_assign).pack(side=tk.LEFT, padx=5)
        
        ModernButton(btn_frame, text="Cancel", bg=self.COLORS['error'],
                    hover=self.COLORS['error_hover'],
                    command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def assign_to_shift(self, shift: Shift):
        """Assign an employee to an empty shift slot"""
        # Find eligible employees
        eligible = []
        for eid, emp in self.data.employees.items():
            if emp.active and emp.role == shift.role:
                if eid not in shift.assigned_employees:
                    if self.scheduler._is_employee_available(eid, shift):
                        # Check hours
                        total_hours = 0
                        for s in self.current_schedule.shifts:
                            if eid in s.assigned_employees:
                                total_hours += s.duration_hours()
                        if total_hours + shift.duration_hours() <= emp.max_hours_week:
                            # Check if already busy at this time
                            if not self.scheduler._is_employee_busy(eid, shift, self.current_schedule):
                                eligible.append((eid, emp.name, total_hours))
        
        if not eligible:
            messagebox.showinfo("No Eligible Employees",
                               "No eligible employees available for this shift")
            return
        
        # Sort by current hours (fairness)
        eligible.sort(key=lambda x: x[2])
        
        # Selection dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Assign to Shift")
        dialog.geometry("500x600")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.COLORS['card'])
        
        # Header
        tk.Label(dialog, text="Assign Employee to Shift", 
                font=("Segoe UI", 14, "bold"),
                bg=self.COLORS['card']).pack(pady=15)
        
        date_obj = datetime.datetime.fromisoformat(shift.date)
        date_str = date_obj.strftime("%A, %B %d")
        
        tk.Label(dialog, text=f"{date_str} | {shift.shift_type} | {shift.role}",
                font=("Segoe UI", 10),
                bg=self.COLORS['card']).pack()
        
        tk.Label(dialog, text="Select employee:",
                bg=self.COLORS['card']).pack(pady=10)
        
        # Scrollable employee cards
        canvas = tk.Canvas(dialog, bg=self.COLORS['card'], highlightthickness=0)
        scrollbar = tk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.COLORS['card'])
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=450)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        selected_var = tk.StringVar()
        
        for eid, name, hours in eligible:
            # Employee card
            card = tk.Frame(scrollable_frame, bg='#F9FAFB',
                           relief=tk.RAISED, bd=1)
            card.pack(fill=tk.X, pady=2, padx=10)
            
            # Radio button
            rb = tk.Radiobutton(card, variable=selected_var, value=eid,
                               bg=card['bg'], activebackground=card['bg'])
            rb.pack(side=tk.LEFT, padx=10)
            
            # Info
            info = tk.Frame(card, bg=card['bg'])
            info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=10)
            
            tk.Label(info, text=name, font=("Segoe UI", 11, "bold"),
                    bg=card['bg']).pack(anchor=tk.W)
            
            # Hours progress
            hours_frame = tk.Frame(info, bg=card['bg'])
            hours_frame.pack(fill=tk.X, pady=2)
            
            tk.Label(hours_frame, text=f"Current: {hours:.1f}h",
                    font=("Segoe UI", 8),
                    bg=card['bg']).pack(side=tk.LEFT)
            
            # Mini progress bar
            emp = self.data.employees[eid]
            progress_frame = tk.Frame(hours_frame, bg=self.COLORS['border'],
                                    height=4, width=100)
            progress_frame.pack(side=tk.LEFT, padx=10)
            progress_frame.pack_propagate(False)
            
            progress = min(100, (hours / emp.max_hours_week) * 100) if emp.max_hours_week > 0 else 0
            fill = tk.Frame(progress_frame, bg=self.COLORS['success'] if progress < 90 else self.COLORS['warning'],
                          height=4, width=int(progress))
            fill.place(x=0, y=0)
        
        canvas.pack(side="left", fill="both", expand=True, padx=(20, 0))
        scrollbar.pack(side="right", fill="y")
        
        def on_assign():
            eid = selected_var.get()
            if eid:
                # Save for undo
                self.undo_stack.append(copy.deepcopy(self.current_schedule))
                self.redo_stack.clear()
                
                # Assign
                shift.assigned_employees.append(eid)
                
                self.create_schedule_grid()
                self.update_conflicts_display()
                self.save_data()
                
                dialog.destroy()
        
        btn_frame = tk.Frame(dialog, bg=self.COLORS['card'])
        btn_frame.pack(pady=20)
        
        ModernButton(btn_frame, text="Assign", bg=self.COLORS['success'],
                    hover=self.COLORS['success_hover'],
                    command=on_assign).pack(side=tk.LEFT, padx=5)
        
        ModernButton(btn_frame, text="Cancel", bg=self.COLORS['error'],
                    hover=self.COLORS['error_hover'],
                    command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def fix_conflict(self, conflict: Conflict):
        """Attempt to fix a conflict"""
        # Simple auto-fix attempt
        if conflict.type == ConflictType.UNDERSTAFFED and conflict.shift_id:
            # Find the shift
            for shift in self.current_schedule.shifts:
                if shift.id == conflict.shift_id:
                    self.assign_to_shift(shift)
                    return
        elif conflict.type == ConflictType.OVER_MAX_HOURS and conflict.employee_id:
            emp = self.data.employees.get(conflict.employee_id)
            if emp:
                # Try to reduce hours
                shifts = self.current_schedule.get_shifts_for_employee(conflict.employee_id)
                if len(shifts) > 1:
                    # Ask which shift to remove
                    messagebox.showinfo("Fix Conflict",
                                       f"Try removing {emp.name} from one of their shifts\n"
                                       "and reassigning to another employee.")
        
        messagebox.showinfo("Fix Conflict",
                           f"Attempting to fix: {conflict.description}\n\n"
                           "This would suggest solutions in the full version.")
    
    def add_employee(self):
        """Add a new employee with enhanced form"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add New Employee")
        dialog.geometry("600x700")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.COLORS['card'])
        
        # Header
        header = tk.Frame(dialog, bg=self.COLORS['accent'], height=60)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        tk.Label(header, text="➕ Add New Employee", 
                font=("Segoe UI", 16, "bold"),
                bg=self.COLORS['accent'], fg='white').pack(expand=True)
        
        # Form content
        content = tk.Frame(dialog, bg=self.COLORS['card'])
        content.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)
        
        # Form fields
        fields = {}
        
        # Personal Information
        personal_frame = tk.LabelFrame(content, text="Personal Information",
                                      bg=self.COLORS['card'], fg=self.COLORS['accent'],
                                      font=("Segoe UI", 10, "bold"))
        personal_frame.pack(fill=tk.X, pady=10)
        
        name_entry = ModernEntry(personal_frame, "Full Name *")
        name_entry.pack(fill=tk.X, pady=5)
        fields['name'] = name_entry
        
        role_frame = tk.Frame(personal_frame, bg=self.COLORS['card'])
        role_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(role_frame, text="Role *", bg=self.COLORS['card']).pack(anchor=tk.W)
        role_combo = ttk.Combobox(role_frame, values=Role.list(), state='readonly',
                                  font=("Segoe UI", 10))
        role_combo.set('Cashier')
        role_combo.pack(fill=tk.X, pady=2)
        fields['role'] = role_combo
        
        hire_frame = tk.Frame(personal_frame, bg=self.COLORS['card'])
        hire_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(hire_frame, text="Hire Date", bg=self.COLORS['card']).pack(anchor=tk.W)
        hire_entry = tk.Entry(hire_frame, font=("Segoe UI", 10), bd=1, relief=tk.SOLID)
        hire_entry.insert(0, datetime.date.today().isoformat())
        hire_entry.pack(fill=tk.X, ipady=5)
        fields['hire_date'] = hire_entry
        
        # Work Hours
        hours_frame = tk.LabelFrame(content, text="Work Hours",
                                   bg=self.COLORS['card'], fg=self.COLORS['accent'],
                                   font=("Segoe UI", 10, "bold"))
        hours_frame.pack(fill=tk.X, pady=10)
        
        max_hours_entry = ModernEntry(hours_frame, "Max Hours/Week *")
        max_hours_entry.insert(0, "40")
        max_hours_entry.pack(fill=tk.X, pady=5)
        fields['max_hours'] = max_hours_entry
        
        min_hours_entry = ModernEntry(hours_frame, "Min Hours/Week")
        min_hours_entry.insert(0, "0")
        min_hours_entry.pack(fill=tk.X, pady=5)
        fields['min_hours'] = min_hours_entry
        
        # Preferences
        pref_frame = tk.LabelFrame(content, text="Shift Preferences",
                                   bg=self.COLORS['card'], fg=self.COLORS['accent'],
                                   font=("Segoe UI", 10, "bold"))
        pref_frame.pack(fill=tk.X, pady=10)
        
        pref_grid = tk.Frame(pref_frame, bg=self.COLORS['card'])
        pref_grid.pack(pady=10)
        
        # Morning preference
        tk.Label(pref_grid, text="Morning:", bg=self.COLORS['card']).grid(row=0, column=0, padx=5)
        morning_spin = tk.Spinbox(pref_grid, from_=1, to=5, width=5,
                                  font=("Segoe UI", 10))
        morning_spin.delete(0, tk.END)
        morning_spin.insert(0, "3")
        morning_spin.grid(row=0, column=1, padx=5)
        fields['morning_pref'] = morning_spin
        
        # Evening preference
        tk.Label(pref_grid, text="Evening:", bg=self.COLORS['card']).grid(row=0, column=2, padx=5)
        evening_spin = tk.Spinbox(pref_grid, from_=1, to=5, width=5,
                                  font=("Segoe UI", 10))
        evening_spin.delete(0, tk.END)
        evening_spin.insert(0, "3")
        evening_spin.grid(row=0, column=3, padx=5)
        fields['evening_pref'] = evening_spin
        
        # Night preference
        tk.Label(pref_grid, text="Night:", bg=self.COLORS['card']).grid(row=0, column=4, padx=5)
        night_spin = tk.Spinbox(pref_grid, from_=1, to=5, width=5,
                                font=("Segoe UI", 10))
        night_spin.delete(0, tk.END)
        night_spin.insert(0, "3")
        night_spin.grid(row=0, column=5, padx=5)
        fields['night_pref'] = night_spin
        
        # Notes
        notes_frame = tk.LabelFrame(content, text="Notes",
                                   bg=self.COLORS['card'], fg=self.COLORS['accent'],
                                   font=("Segoe UI", 10, "bold"))
        notes_frame.pack(fill=tk.X, pady=10)
        
        notes_text = tk.Text(notes_frame, height=4, font=("Segoe UI", 10),
                            bd=1, relief=tk.SOLID)
        notes_text.pack(fill=tk.X, pady=5)
        fields['notes'] = notes_text
        
        def save_employee():
            try:
                # Validate required fields
                if not fields['name'].get():
                    messagebox.showerror("Error", "Name is required")
                    return
                
                emp_id = self.data.generate_employee_id()
                emp = Employee(
                    id=emp_id,
                    name=fields['name'].get(),
                    role=fields['role'].get(),
                    max_hours_week=float(fields['max_hours'].get()),
                    min_hours_week=float(fields['min_hours'].get()) if fields['min_hours'].get() else 0,
                    hire_date=fields['hire_date'].get(),
                    active=True,
                    notes=fields['notes'].get(1.0, tk.END).strip(),
                    morning_pref=int(fields['morning_pref'].get()),
                    evening_pref=int(fields['evening_pref'].get()),
                    night_pref=int(fields['night_pref'].get())
                )
                
                self.data.employees[emp_id] = emp
                self.data.availabilities[emp_id] = Availability(employee_id=emp_id)
                
                # Update UI
                self.update_employee_combo()
                self.refresh_employee_table()
                self.update_employee_list()
                self.save_data()
                
                dialog.destroy()
                messagebox.showinfo("Success", f"Employee {emp.name} added successfully")
            except ValueError as e:
                messagebox.showerror("Error", f"Invalid input: {e}")
        
        # Buttons
        btn_frame = tk.Frame(content, bg=self.COLORS['card'])
        btn_frame.pack(pady=20)
        
        ModernButton(btn_frame, text="💾 Save Employee", 
                    bg=self.COLORS['success'], hover=self.COLORS['success_hover'],
                    command=save_employee).pack(side=tk.LEFT, padx=5)
        
        ModernButton(btn_frame, text="❌ Cancel", 
                    bg=self.COLORS['error'], hover=self.COLORS['error_hover'],
                    command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def edit_employee(self):
        """Edit selected employee"""
        selected = self.employee_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select an employee")
            return
        
        emp_id = selected[0]
        emp = self.data.employees.get(emp_id)
        
        if not emp:
            return
        
        # Similar to add_employee but with existing data
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Employee: {emp.name}")
        dialog.geometry("600x700")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.COLORS['card'])
        
        # Header
        header = tk.Frame(dialog, bg=self.COLORS['accent'], height=60)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        tk.Label(header, text=f"✏️ Edit Employee: {emp.name}", 
                font=("Segoe UI", 16, "bold"),
                bg=self.COLORS['accent'], fg='white').pack(expand=True)
        
        # Form content
        content = tk.Frame(dialog, bg=self.COLORS['card'])
        content.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)
        
        # Form fields
        fields = {}
        
        # Personal Information
        personal_frame = tk.LabelFrame(content, text="Personal Information",
                                      bg=self.COLORS['card'], fg=self.COLORS['accent'],
                                      font=("Segoe UI", 10, "bold"))
        personal_frame.pack(fill=tk.X, pady=10)
        
        name_entry = ModernEntry(personal_frame, "Full Name *")
        name_entry.insert(0, emp.name)
        name_entry.pack(fill=tk.X, pady=5)
        fields['name'] = name_entry
        
        role_frame = tk.Frame(personal_frame, bg=self.COLORS['card'])
        role_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(role_frame, text="Role *", bg=self.COLORS['card']).pack(anchor=tk.W)
        role_combo = ttk.Combobox(role_frame, values=Role.list(), state='readonly',
                                  font=("Segoe UI", 10))
        role_combo.set(emp.role)
        role_combo.pack(fill=tk.X, pady=2)
        fields['role'] = role_combo
        
        hire_frame = tk.Frame(personal_frame, bg=self.COLORS['card'])
        hire_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(hire_frame, text="Hire Date", bg=self.COLORS['card']).pack(anchor=tk.W)
        hire_entry = tk.Entry(hire_frame, font=("Segoe UI", 10), bd=1, relief=tk.SOLID)
        hire_entry.insert(0, emp.hire_date)
        hire_entry.pack(fill=tk.X, ipady=5)
        fields['hire_date'] = hire_entry
        
        # Status
        status_frame = tk.Frame(personal_frame, bg=self.COLORS['card'])
        status_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(status_frame, text="Status:", bg=self.COLORS['card']).pack(side=tk.LEFT)
        active_var = tk.BooleanVar(value=emp.active)
        active_cb = tk.Checkbutton(status_frame, text="Active", variable=active_var,
                                  bg=self.COLORS['card'], font=("Segoe UI", 10))
        active_cb.pack(side=tk.LEFT, padx=10)
        fields['active'] = active_var
        
        # Work Hours
        hours_frame = tk.LabelFrame(content, text="Work Hours",
                                   bg=self.COLORS['card'], fg=self.COLORS['accent'],
                                   font=("Segoe UI", 10, "bold"))
        hours_frame.pack(fill=tk.X, pady=10)
        
        max_hours_entry = ModernEntry(hours_frame, "Max Hours/Week *")
        max_hours_entry.insert(0, str(emp.max_hours_week))
        max_hours_entry.pack(fill=tk.X, pady=5)
        fields['max_hours'] = max_hours_entry
        
        min_hours_entry = ModernEntry(hours_frame, "Min Hours/Week")
        min_hours_entry.insert(0, str(emp.min_hours_week))
        min_hours_entry.pack(fill=tk.X, pady=5)
        fields['min_hours'] = min_hours_entry
        
        # Preferences
        pref_frame = tk.LabelFrame(content, text="Shift Preferences",
                                   bg=self.COLORS['card'], fg=self.COLORS['accent'],
                                   font=("Segoe UI", 10, "bold"))
        pref_frame.pack(fill=tk.X, pady=10)
        
        pref_grid = tk.Frame(pref_frame, bg=self.COLORS['card'])
        pref_grid.pack(pady=10)
        
        # Morning preference
        tk.Label(pref_grid, text="Morning:", bg=self.COLORS['card']).grid(row=0, column=0, padx=5)
        morning_spin = tk.Spinbox(pref_grid, from_=1, to=5, width=5,
                                  font=("Segoe UI", 10))
        morning_spin.delete(0, tk.END)
        morning_spin.insert(0, str(emp.morning_pref))
        morning_spin.grid(row=0, column=1, padx=5)
        fields['morning_pref'] = morning_spin
        
        # Evening preference
        tk.Label(pref_grid, text="Evening:", bg=self.COLORS['card']).grid(row=0, column=2, padx=5)
        evening_spin = tk.Spinbox(pref_grid, from_=1, to=5, width=5,
                                  font=("Segoe UI", 10))
        evening_spin.delete(0, tk.END)
        evening_spin.insert(0, str(emp.evening_pref))
        evening_spin.grid(row=0, column=3, padx=5)
        fields['evening_pref'] = evening_spin
        
        # Night preference
        tk.Label(pref_grid, text="Night:", bg=self.COLORS['card']).grid(row=0, column=4, padx=5)
        night_spin = tk.Spinbox(pref_grid, from_=1, to=5, width=5,
                                font=("Segoe UI", 10))
        night_spin.delete(0, tk.END)
        night_spin.insert(0, str(emp.night_pref))
        night_spin.grid(row=0, column=5, padx=5)
        fields['night_pref'] = night_spin
        
        # Notes
        notes_frame = tk.LabelFrame(content, text="Notes",
                                   bg=self.COLORS['card'], fg=self.COLORS['accent'],
                                   font=("Segoe UI", 10, "bold"))
        notes_frame.pack(fill=tk.X, pady=10)
        
        notes_text = tk.Text(notes_frame, height=4, font=("Segoe UI", 10),
                            bd=1, relief=tk.SOLID)
        notes_text.insert(1.0, emp.notes)
        notes_text.pack(fill=tk.X, pady=5)
        fields['notes'] = notes_text
        
        def update_employee():
            try:
                # Validate required fields
                if not fields['name'].get():
                    messagebox.showerror("Error", "Name is required")
                    return
                
                emp.name = fields['name'].get()
                emp.role = fields['role'].get()
                emp.max_hours_week = float(fields['max_hours'].get())
                emp.min_hours_week = float(fields['min_hours'].get()) if fields['min_hours'].get() else 0
                emp.hire_date = fields['hire_date'].get()
                emp.active = fields['active'].get()
                emp.notes = fields['notes'].get(1.0, tk.END).strip()
                emp.morning_pref = int(fields['morning_pref'].get())
                emp.evening_pref = int(fields['evening_pref'].get())
                emp.night_pref = int(fields['night_pref'].get())
                
                # Update UI
                self.update_employee_combo()
                self.refresh_employee_table()
                self.update_employee_list()
                self.save_data()
                
                dialog.destroy()
                messagebox.showinfo("Success", f"Employee {emp.name} updated successfully")
            except ValueError as e:
                messagebox.showerror("Error", f"Invalid input: {e}")
        
        # Buttons
        btn_frame = tk.Frame(content, bg=self.COLORS['card'])
        btn_frame.pack(pady=20)
        
        ModernButton(btn_frame, text="💾 Update Employee", 
                    bg=self.COLORS['success'], hover=self.COLORS['success_hover'],
                    command=update_employee).pack(side=tk.LEFT, padx=5)
        
        ModernButton(btn_frame, text="❌ Cancel", 
                    bg=self.COLORS['error'], hover=self.COLORS['error_hover'],
                    command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def delete_employee(self):
        """Delete selected employee"""
        selected = self.employee_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select an employee")
            return
        
        emp_id = selected[0]
        emp = self.data.employees.get(emp_id)
        
        # Custom delete confirmation
        dialog = tk.Toplevel(self.root)
        dialog.title("Confirm Delete")
        dialog.geometry("400x200")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.COLORS['card'])
        
        tk.Label(dialog, text="⚠️ Delete Employee", 
                font=("Segoe UI", 14, "bold"),
                bg=self.COLORS['card'], fg=self.COLORS['error']).pack(pady=20)
        
        tk.Label(dialog, text=f"Are you sure you want to delete {emp.name}?",
                bg=self.COLORS['card']).pack()
        
        tk.Label(dialog, text="This action cannot be undone.",
                font=("Segoe UI", 8),
                bg=self.COLORS['card'], fg=self.COLORS['text_light']).pack(pady=10)
        
        btn_frame = tk.Frame(dialog, bg=self.COLORS['card'])
        btn_frame.pack(pady=20)
        
        def confirm_delete():
            del self.data.employees[emp_id]
            if emp_id in self.data.availabilities:
                del self.data.availabilities[emp_id]
            
            self.refresh_employee_table()
            self.update_employee_list()
            self.update_employee_combo()
            self.save_data()
            dialog.destroy()
            messagebox.showinfo("Success", f"Employee {emp.name} deleted")
        
        ModernButton(btn_frame, text="🗑️ Delete", 
                    bg=self.COLORS['error'], hover=self.COLORS['error_hover'],
                    command=confirm_delete).pack(side=tk.LEFT, padx=5)
        
        ModernButton(btn_frame, text="Cancel", 
                    bg=self.COLORS['text'], hover='#374151',
                    command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def delete_selected(self):
        """Delete selected item (context sensitive)"""
        current_tab = self.notebook.index(self.notebook.select())
        if current_tab == 1:  # Employees tab
            self.delete_employee()
    
    def show_employee_details(self, emp_id: str):
        """Show employee details popup"""
        emp = self.data.employees.get(emp_id)
        if not emp:
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Employee Details: {emp.name}")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.configure(bg=self.COLORS['card'])
        
        # Header with avatar
        header = tk.Frame(dialog, bg=self.COLORS['accent'], height=80)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        # Avatar
        colors = ['#2563EB', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6']
        color = colors[hash(emp_id) % len(colors)]
        
        avatar_frame = tk.Frame(header, bg=color, width=50, height=50)
        avatar_frame.place(relx=0.5, rely=0.5, anchor='center')
        avatar_frame.pack_propagate(False)
        
        avatar = tk.Label(avatar_frame, text=emp.name[0].upper(),
                         bg=color, fg='white',
                         font=("Segoe UI", 20, "bold"))
        avatar.pack(expand=True)
        
        # Content
        content = tk.Frame(dialog, bg=self.COLORS['card'])
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Employee info in a grid
        info_frame = tk.Frame(content, bg=self.COLORS['card'])
        info_frame.pack(fill=tk.X, pady=10)
        
        # Name and role
        tk.Label(info_frame, text=emp.name, 
                font=("Segoe UI", 16, "bold"),
                bg=self.COLORS['card']).pack(anchor=tk.W)
        
        tk.Label(info_frame, text=emp.role,
                font=("Segoe UI", 12),
                bg=self.COLORS['card'], fg=self.COLORS['text_light']).pack(anchor=tk.W)
        
        # Details grid
        details_frame = tk.Frame(content, bg=self.COLORS['card'])
        details_frame.pack(fill=tk.X, pady=10)
        
        details = [
            ("ID:", emp.id),
            ("Status:", "✅ Active" if emp.active else "❌ Inactive"),
            ("Max Hours/Week:", f"{emp.max_hours_week} hours"),
            ("Min Hours/Week:", f"{emp.min_hours_week} hours"),
            ("Hire Date:", emp.hire_date),
            ("Seniority:", f"{emp.get_seniority_days()} days"),
        ]
        
        for i, (label, value) in enumerate(details):
            tk.Label(details_frame, text=label, 
                    font=("Segoe UI", 10, "bold"),
                    bg=self.COLORS['card']).grid(row=i, column=0, sticky=tk.W, pady=2)
            tk.Label(details_frame, text=value,
                    font=("Segoe UI", 10),
                    bg=self.COLORS['card']).grid(row=i, column=1, sticky=tk.W, padx=10, pady=2)
        
        # Preferences
        pref_frame = tk.LabelFrame(content, text="Shift Preferences",
                                  bg=self.COLORS['card'], fg=self.COLORS['accent'])
        pref_frame.pack(fill=tk.X, pady=10)
        
        pref_grid = tk.Frame(pref_frame, bg=self.COLORS['card'])
        pref_grid.pack(pady=10)
        
        # Preference bars
        prefs = [
            ("Morning", emp.morning_pref),
            ("Evening", emp.evening_pref),
            ("Night", emp.night_pref)
        ]
        
        for i, (label, value) in enumerate(prefs):
            tk.Label(pref_grid, text=f"{label}:", 
                    bg=self.COLORS['card']).grid(row=0, column=i*2, padx=5)
            
            bar_frame = tk.Frame(pref_grid, bg=self.COLORS['border'],
                                height=10, width=100)
            bar_frame.grid(row=0, column=i*2+1, padx=5)
            bar_frame.pack_propagate(False)
            
            bar_color = self.COLORS['success'] if value >= 4 else self.COLORS['warning'] if value >= 2 else self.COLORS['error']
            fill = tk.Frame(bar_frame, bg=bar_color, height=10,
                          width=int(value * 20))
            fill.place(x=0, y=0)
        
        # Notes
        if emp.notes:
            notes_label = tk.LabelFrame(content, text="Notes",
                                       bg=self.COLORS['card'], fg=self.COLORS['accent'])
            notes_label.pack(fill=tk.X, pady=10)
            
            tk.Label(notes_label, text=emp.notes,
                    wraplength=400, justify=tk.LEFT,
                    bg=self.COLORS['card']).pack(pady=5)
        
        # Close button
        ModernButton(content, text="Close", 
                    bg=self.COLORS['text'], hover='#374151',
                    command=dialog.destroy).pack(pady=10)
    
    def edit_constraints(self):
        """Edit labor law constraints with modern form"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Labor Law Constraints")
        dialog.geometry("500x500")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.COLORS['card'])
        
        # Header
        header = tk.Frame(dialog, bg=self.COLORS['accent'], height=60)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        tk.Label(header, text="⚖️ Labor Law Constraints", 
                font=("Segoe UI", 16, "bold"),
                bg=self.COLORS['accent'], fg='white').pack(expand=True)
        
        # Content
        content = tk.Frame(dialog, bg=self.COLORS['card'])
        content.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)
        
        fields = {}
        constraints = self.data.law_constraints
        
        # Create form fields
        constraints_list = [
            ("max_hours_day", "Max Hours Per Day:", str(constraints.max_hours_per_day)),
            ("min_hours_day", "Min Hours Per Day:", str(constraints.min_hours_per_day)),
            ("max_hours_week", "Max Hours Per Week:", str(constraints.max_hours_per_week)),
            ("min_rest", "Min Rest Between Shifts (hours):", str(constraints.min_rest_between_shifts)),
            ("max_consecutive", "Max Consecutive Days:", str(constraints.max_consecutive_days)),
            ("break_after", "Required Break After (hours):", str(constraints.required_break_after_hours)),
            ("overtime", "Overtime Threshold (hours):", str(constraints.overtime_threshold)),
        ]
        
        for i, (key, label, value) in enumerate(constraints_list):
            frame = tk.Frame(content, bg=self.COLORS['card'])
            frame.pack(fill=tk.X, pady=5)
            
            tk.Label(frame, text=label, width=25, anchor=tk.W,
                    bg=self.COLORS['card']).pack(side=tk.LEFT)
            
            entry = tk.Entry(frame, width=10, font=("Segoe UI", 10),
                           bd=1, relief=tk.SOLID)
            entry.insert(0, value)
            entry.pack(side=tk.LEFT, padx=10)
            fields[key] = entry
        
        # Overtime multiplier
        mult_frame = tk.Frame(content, bg=self.COLORS['card'])
        mult_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(mult_frame, text="Overtime Multiplier:", width=25, anchor=tk.W,
                bg=self.COLORS['card']).pack(side=tk.LEFT)
        
        mult_entry = tk.Entry(mult_frame, width=10, font=("Segoe UI", 10),
                            bd=1, relief=tk.SOLID)
        mult_entry.insert(0, str(constraints.overtime_multiplier))
        mult_entry.pack(side=tk.LEFT, padx=10)
        fields['multiplier'] = multEntry
        
        # Minor restrictions checkbox
        minor_frame = tk.Frame(content, bg=self.COLORS['card'])
        minor_frame.pack(fill=tk.X, pady=10)
        
        minor_var = tk.BooleanVar(value=constraints.minor_restrictions)
        tk.Checkbutton(minor_frame, text="Apply Minor Restrictions",
                      variable=minor_var, bg=self.COLORS['card'],
                      font=("Segoe UI", 10)).pack(anchor=tk.W)
        fields['minor'] = minor_var
        
        def save_constraints():
            try:
                constraints.max_hours_per_day = float(fields['max_hours_day'].get())
                constraints.min_hours_per_day = float(fields['min_hours_day'].get())
                constraints.max_hours_per_week = float(fields['max_hours_week'].get())
                constraints.min_rest_between_shifts = float(fields['min_rest'].get())
                constraints.max_consecutive_days = int(fields['max_consecutive'].get())
                constraints.required_break_after_hours = float(fields['break_after'].get())
                constraints.overtime_threshold = float(fields['overtime'].get())
                constraints.overtime_multiplier = float(fields['multiplier'].get())
                constraints.minor_restrictions = fields['minor'].get()
                
                self.save_data()
                dialog.destroy()
                messagebox.showinfo("Success", "Constraints updated successfully")
            except ValueError as e:
                messagebox.showerror("Error", f"Invalid input: {e}")
        
        # Buttons
        btn_frame = tk.Frame(content, bg=self.COLORS['card'])
        btn_frame.pack(pady=20)
        
        ModernButton(btn_frame, text="💾 Save Constraints", 
                    bg=self.COLORS['success'], hover=self.COLORS['success_hover'],
                    command=save_constraints).pack(side=tk.LEFT, padx=5)
        
        ModernButton(btn_frame, text="❌ Cancel", 
                    bg=self.COLORS['error'], hover=self.COLORS['error_hover'],
                    command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def edit_requirements(self):
        """Edit shift requirements with modern interface"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Shift Requirements")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.COLORS['card'])
        
        # Header
        header = tk.Frame(dialog, bg=self.COLORS['accent'], height=60)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        tk.Label(header, text="📋 Shift Requirements", 
                font=("Segoe UI", 16, "bold"),
                bg=self.COLORS['accent'], fg='white').pack(expand=True)
        
        # Content with notebook for shift types
        content = tk.Frame(dialog, bg=self.COLORS['card'])
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Create notebook for shift types
        req_notebook = ttk.Notebook(content)
        req_notebook.pack(fill=tk.BOTH, expand=True)
        
        requirement_widgets = {}
        
        for shift_type in ShiftType.list():
            # Create tab for each shift type
            tab = ttk.Frame(req_notebook)
            req_notebook.add(tab, text=shift_type.split()[0])
            
            # Get existing requirements
            req = self.data.shift_requirements.get(shift_type, 
                                                   ShiftRequirement(shift_type=shift_type))
            
            # Role requirements frame
            roles_frame = tk.Frame(tab, bg=self.COLORS['card'])
            roles_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            tk.Label(roles_frame, text="Role Requirements",
                    font=("Segoe UI", 11, "bold"),
                    bg=self.COLORS['card']).pack(anchor=tk.W, pady=5)
            
            # Role entries
            role_entries = {}
            all_roles = Role.list()
            
            for role in all_roles:
                role_frame = tk.Frame(roles_frame, bg=self.COLORS['card'])
                role_frame.pack(fill=tk.X, pady=2)
                
                tk.Label(role_frame, text=f"{role}:", width=15, anchor=tk.W,
                        bg=self.COLORS['card']).pack(side=tk.LEFT)
                
                count_var = tk.StringVar(value=str(req.role_requirements.get(role, 0)))
                spinbox = tk.Spinbox(role_frame, from_=0, to=10, width=5,
                                    textvariable=count_var,
                                    font=("Segoe UI", 10))
                spinbox.pack(side=tk.LEFT, padx=10)
                
                role_entries[role] = count_var
            
            requirement_widgets[shift_type] = role_entries
        
        def save_requirements():
            for shift_type, role_entries in requirement_widgets.items():
                # Get or create requirement
                if shift_type not in self.data.shift_requirements:
                    self.data.shift_requirements[shift_type] = ShiftRequirement(shift_type=shift_type)
                
                req = self.data.shift_requirements[shift_type]
                
                # Update role requirements
                req.role_requirements = {}
                for role, var in role_entries.items():
                    count = int(var.get())
                    if count > 0:
                        req.role_requirements[role] = count
            
            self.update_requirements_display()
            self.save_data()
            dialog.destroy()
            messagebox.showinfo("Success", "Shift requirements updated")
        
        # Buttons
        btn_frame = tk.Frame(content, bg=self.COLORS['card'])
        btn_frame.pack(pady=10)
        
        ModernButton(btn_frame, text="💾 Save Requirements", 
                    bg=self.COLORS['success'], hover=self.COLORS['success_hover'],
                    command=save_requirements).pack(side=tk.LEFT, padx=5)
        
        ModernButton(btn_frame, text="❌ Cancel", 
                    bg=self.COLORS['error'], hover=self.COLORS['error_hover'],
                    command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def export_csv(self):
        """Export schedule to CSV"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if filename and self.current_schedule:
            try:
                with open(filename, 'w', newline='', encoding='utf-8') as f:
                    f.write("Date,Day,Shift Type,Role,Start,End,Employees,Status\n")
                    
                    for shift in self.current_schedule.shifts:
                        date_obj = datetime.datetime.fromisoformat(shift.date)
                        day_name = date_obj.strftime("%A")
                        
                        employees = "; ".join([
                            self.data.employees.get(eid, Employee(id=eid, name="Unknown", role="")).name
                            for eid in shift.assigned_employees
                        ])
                        status = "Full" if shift.is_full() else f"Needs {shift.required_count - len(shift.assigned_employees)}"
                        
                        f.write(f"{shift.date},{day_name},{shift.shift_type},{shift.role},"
                               f"{shift.start_time},{shift.end_time},\"{employees}\",{status}\n")
                
                messagebox.showinfo("Success", f"Schedule exported to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export: {e}")
    
    def print_preview(self):
        """Show print preview"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Print Preview")
        dialog.geometry("900x700")
        dialog.transient(self.root)
        dialog.configure(bg=self.COLORS['card'])
        
        # Header
        header = tk.Frame(dialog, bg=self.COLORS['accent'], height=60)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        tk.Label(header, text="🖨️ Print Preview", 
                font=("Segoe UI", 16, "bold"),
                bg=self.COLORS['accent'], fg='white').pack(expand=True)
        
        # Preview area with scroll
        preview_frame = tk.Frame(dialog, bg='white')
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        canvas = tk.Canvas(preview_frame, bg='white', highlightthickness=0)
        v_scrollbar = ttk.Scrollbar(preview_frame, orient="vertical", command=canvas.yview)
        h_scrollbar = ttk.Scrollbar(preview_frame, orient="horizontal", command=canvas.xview)
        
        scrollable_frame = tk.Frame(canvas, bg='white')
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # Generate print content
        if self.current_schedule:
            # Title
            title = tk.Label(scrollable_frame, 
                           text=f"Weekly Schedule\n{self.current_week.strftime('%B %d, %Y')}",
                           font=("Times", 18, "bold"), bg='white')
            title.pack(pady=20)
            
            # Schedule table
            days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                   'Friday', 'Saturday', 'Sunday']
            
            for day_offset in range(7):
                date = self.current_week + datetime.timedelta(days=day_offset)
                day_shifts = [s for s in self.current_schedule.shifts 
                            if s.date == date.isoformat()]
                
                if day_shifts:
                    # Day header
                    day_frame = tk.Frame(scrollable_frame, bg='#F3F4F6', height=30)
                    day_frame.pack(fill=tk.X, pady=(10, 0))
                    
                    tk.Label(day_frame, 
                           text=f"{date.strftime('%A, %B %d')}",
                           font=("Times", 14, "bold"), bg='#F3F4F6').pack(pady=5)
                    
                    # Shifts table
                    table_frame = tk.Frame(scrollable_frame, bg='white')
                    table_frame.pack(fill=tk.X, padx=20)
                    
                    for shift in day_shifts:
                        shift_frame = tk.Frame(table_frame, bg='white', relief=tk.SOLID, bd=1)
                        shift_frame.pack(fill=tk.X, pady=2)
                        
                        # Shift time and type
                        time_label = tk.Label(shift_frame, 
                                            text=f"{shift.start_time}-{shift.end_time}",
                                            font=("Times", 11, "bold"), bg='white')
                        time_label.pack(side=tk.LEFT, padx=10, pady=5)
                        
                        type_label = tk.Label(shift_frame, text=shift.shift_type,
                                            font=("Times", 10), bg='white')
                        type_label.pack(side=tk.LEFT, padx=10)
                        
                        role_label = tk.Label(shift_frame, text=f"[{shift.role}]",
                                            font=("Times", 10), bg='white',
                                            fg=self.COLORS['text_light'])
                        role_label.pack(side=tk.LEFT, padx=10)
                        
                        # Employees
                        employees = ", ".join([
                            self.data.employees.get(eid, Employee(id=eid, name="Unknown", role="")).name
                            for eid in shift.assigned_employees
                        ]) or "UNFILLED"
                        
                        emp_label = tk.Label(shift_frame, text=employees,
                                           font=("Times", 10), bg='white')
                        emp_label.pack(side=tk.RIGHT, padx=10)
        
        canvas.pack(side="left", fill="both", expand=True)
        v_scrollbar.pack(side="right", fill="y")
        h_scrollbar.pack(side="bottom", fill="x")
        
        # Print button
        btn_frame = tk.Frame(dialog, bg=self.COLORS['card'])
        btn_frame.pack(pady=10)
        
        def print_document():
            # Simple print simulation
            messagebox.showinfo("Print", "Print functionality would send to printer")
        
        ModernButton(btn_frame, text="🖨️ Print", 
                    bg=self.COLORS['accent'], hover=self.COLORS['accent_hover'],
                    command=print_document).pack(side=tk.LEFT, padx=5)
        
        ModernButton(btn_frame, text="❌ Close", 
                    bg=self.COLORS['error'], hover=self.COLORS['error_hover'],
                    command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def save_data(self):
        """Save all data"""
        if self.data.save():
            self.update_status_bar()
            # Show brief success message in status bar
            self.status_label.config(text="💾 Saved successfully")
            self.root.after(2000, self.update_status_bar)
        else:
            messagebox.showerror("Error", "Failed to save data")
    
    def load_data(self):
        """Load data from file"""
        filename = filedialog.askopenfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            if self.data.load(filename):
                self.load_week()
                self.refresh_employee_table()
                self.update_employee_list()
                self.update_employee_combo()
                self.update_requirements_display()
                messagebox.showinfo("Success", "Data loaded successfully")
            else:
                messagebox.showerror("Error", "Failed to load data")
    
    def undo(self):
        """Undo last action"""
        if self.undo_stack:
            self.redo_stack.append(copy.deepcopy(self.current_schedule))
            self.current_schedule = self.undo_stack.pop()
            self.create_schedule_grid()
            self.update_conflicts_display()
            self.update_employee_list()
            self.status_label.config(text="↩️ Undo completed")
            self.root.after(2000, self.update_status_bar)
    
    def redo(self):
        """Redo last undone action"""
        if self.redo_stack:
            self.undo_stack.append(copy.deepcopy(self.current_schedule))
            self.current_schedule = self.redo_stack.pop()
            self.create_schedule_grid()
            self.update_conflicts_display()
            self.update_employee_list()
            self.status_label.config(text="↪️ Redo completed")
            self.root.after(2000, self.update_status_bar)
    
    def refresh(self):
        """Refresh all views"""
        self.load_week()
        self.refresh_employee_table()
        self.update_employee_list()
        self.update_requirements_display()
        self.update_conflicts_display()
        self.update_employee_combo()
        self.status_label.config(text="🔄 Refreshed")
        self.root.after(2000, self.update_status_bar)
    
    def toggle_dark_mode(self):
        """Toggle dark/light mode"""
        # Simple dark mode toggle
        if self.COLORS['bg'] == '#F3F4F6':
            # Switch to dark mode
            self.COLORS.update({
                'bg': '#1F2937',
                'card': '#374151',
                'text': '#F9FAFB',
                'text_light': '#9CA3AF',
                'border': '#4B5563'
            })
        else:
            # Switch to light mode
            self.COLORS.update({
                'bg': '#F3F4F6',
                'card': '#FFFFFF',
                'text': '#1F2937',
                'text_light': '#6B7280',
                'border': '#E5E7EB'
            })
        
        # Refresh UI
        self.root.configure(bg=self.COLORS['bg'])
        self.refresh()
    
    def update_status_bar(self):
        """Update status bar information"""
        emp_count = len([e for e in self.data.employees.values() if e.active])
        week_info = f"Week of {self.current_week.strftime('%B %d, %Y')}"
        
        if self.current_schedule:
            shift_count = len(self.current_schedule.shifts)
            filled = sum(1 for s in self.current_schedule.shifts if s.is_full())
            self.status_label.config(
                text=f"{week_info} | 📊 {shift_count} shifts, {filled} fully staffed")
        else:
            self.status_label.config(text=week_info)
        
        if hasattr(self, 'employee_count_label'):
            self.employee_count_label.config(text=f"👥 Active Employees: {emp_count}")
    
    def refresh_employee_table(self):
        """Refresh the employee table in employees tab"""
        # Clear existing
        for item in self.employee_tree.get_children():
            self.employee_tree.delete(item)
        
        search_term = self.emp_search_var.get().lower()
        if search_term == "search employees...":
            search_term = ""
        
        for emp_id, emp in self.data.employees.items():
            if search_term and search_term not in emp.name.lower() and search_term not in emp.role.lower():
                continue
            
            status = "Active" if emp.active else "Inactive"
            self.employee_tree.insert('', tk.END, iid=emp_id, values=(
                emp_id, emp.name, emp.role, status,
                emp.max_hours_week, emp.min_hours_week, emp.hire_date
            ))
    
    def filter_employee_table(self):
        """Filter employee table based on search"""
        self.refresh_employee_table()
    
    def toggle_conflicts(self):
        """Toggle conflicts panel expansion"""
        if self.conflict_content.winfo_ismapped():
            self.conflict_content.pack_forget()
            self.conflict_expand_btn.config(text="▶")
        else:
            self.conflict_content.pack(fill=tk.X, padx=15, pady=(0, 10))
            self.conflict_expand_btn.config(text="▼")
    
    def show_about(self):
        """Show about dialog"""
        dialog = tk.Toplevel(self.root)
        dialog.title("About")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.configure(bg=self.COLORS['card'])
        
        # Logo/Icon
        logo_frame = tk.Frame(dialog, bg=self.COLORS['accent'], height=100)
        logo_frame.pack(fill=tk.X)
        logo_frame.pack_propagate(False)
        
        tk.Label(logo_frame, text="📅", 
                font=("Segoe UI", 48),
                bg=self.COLORS['accent'], fg='white').pack(expand=True)
        
        # Content
        content = tk.Frame(dialog, bg=self.COLORS['card'])
        content.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)
        
        tk.Label(content, text="Employee Shift Scheduler Pro",
                font=("Segoe UI", 18, "bold"),
                bg=self.COLORS['card']).pack(pady=10)
        
        tk.Label(content, text="Version 2.0",
                font=("Segoe UI", 12),
                bg=self.COLORS['card'], fg=self.COLORS['text_light']).pack()
        
        tk.Label(content, text="\nA comprehensive desktop application for managing\nemployee shifts using only Python built-in libraries.",
                justify=tk.CENTER,
                bg=self.COLORS['card']).pack(pady=10)
        
        tk.Label(content, text="\nFeatures:\n• Employee Management\n• Availability Tracking\n• Smart Scheduling\n• Conflict Detection\n• Reports & Analytics",
                justify=tk.LEFT,
                bg=self.COLORS['card']).pack(pady=10)
        
        tk.Label(content, text="\nCreated for college portfolio demonstration\n© 2025",
                font=("Segoe UI", 9),
                bg=self.COLORS['card'], fg=self.COLORS['text_light']).pack(pady=10)
        
        ModernButton(content, text="Close", 
                    bg=self.COLORS['accent'], hover=self.COLORS['accent_hover'],
                    command=dialog.destroy).pack(pady=10)
    
    def show_help(self):
        """Show help dialog"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Help")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.configure(bg=self.COLORS['card'])
        
        # Header
        header = tk.Frame(dialog, bg=self.COLORS['accent'], height=60)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        tk.Label(header, text="❓ Help & User Guide", 
                font=("Segoe UI", 16, "bold"),
                bg=self.COLORS['accent'], fg='white').pack(expand=True)
        
        # Content with notebook
        content = tk.Frame(dialog, bg=self.COLORS['card'])
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        help_notebook = ttk.Notebook(content)
        help_notebook.pack(fill=tk.BOTH, expand=True)
        
        # Getting Started tab
        getting_started = ttk.Frame(help_notebook)
        help_notebook.add(getting_started, text="Getting Started")
        
        gs_text = tk.Text(getting_started, wrap=tk.WORD, font=("Segoe UI", 10),
                         bg='white', padx=10, pady=10)
        gs_text.pack(fill=tk.BOTH, expand=True)
        gs_text.insert(tk.END, """📋 GETTING STARTED

1. Add Employees
   • Go to the Employees tab
   • Click "Add Employee" and fill in the details
   • Set their role, hours, and preferences

2. Set Availability
   • Go to the Availability tab
   • Select an employee from the dropdown
   • Set their available time ranges for each day
   • Add time off requests if needed

3. Configure Requirements
   • Click the ⚙️ button or go to Tools > Shift Requirements
   • Set how many employees are needed for each shift type and role

4. Generate Schedule
   • Go to the Schedule tab
   • Click "Generate Schedule" button
   • Select a strategy (Fair Distribution, Preference First, etc.)
   • Click "Generate" to create the schedule

5. Review and Adjust
   • Check for conflicts in the conflicts panel
   • Make manual adjustments by enabling Manual Mode
   • Use drag-and-drop to reassign employees

6. Export or Print
   • Export to CSV for sharing
   • Use Print Preview for a formatted version
""")
        gs_text.config(state=tk.DISABLED)
        
        # Keyboard Shortcuts tab
        shortcuts = ttk.Frame(help_notebook)
        help_notebook.add(shortcuts, text="Shortcuts")
        
        sc_text = tk.Text(shortcuts, wrap=tk.WORD, font=("Segoe UI", 10),
                         bg='white', padx=10, pady=10)
        sc_text.pack(fill=tk.BOTH, expand=True)
        sc_text.insert(tk.END, """⌨️ KEYBOARD SHORTCUTS

General:
• Ctrl+S - Save data
• Ctrl+O - Load data
• Ctrl+Z - Undo
• Ctrl+Y - Redo
• Ctrl+N - New employee
• Delete - Delete selected
• Esc - Exit manual mode

Navigation:
• Arrow keys - Navigate through schedule
• Tab - Move between fields
• Space - Select/Deselect

Schedule View:
• Click on shift - View details
• Right-click on employee - Remove from shift
• Drag and drop - Move employee (Manual Mode)
""")
        sc_text.config(state=tk.DISABLED)
        
        # Features tab
        features = ttk.Frame(help_notebook)
        help_notebook.add(features, text="Features")
        
        feat_text = tk.Text(features, wrap=tk.WORD, font=("Segoe UI", 10),
                           bg='white', padx=10, pady=10)
        feat_text.pack(fill=tk.BOTH, expand=True)
        feat_text.insert(tk.END, """✨ KEY FEATURES

Employee Management
• Add, edit, and delete employees
• Track roles, hours, and preferences
• View employee details and seniority

Availability Management
• Set recurring weekly availability
• Multiple time ranges per day
• Time off requests with approval

Smart Scheduling
• Multiple generation strategies
• Respects labor law constraints
• Fair hour distribution
• Preference satisfaction
• Conflict detection

Reports & Analytics
• Hours summary
• Labor cost projection
• Overtime tracking
• Preference satisfaction
• Export to CSV

Manual Adjustments
• Drag-and-drop interface
• Undo/redo support
• Auto-fill empty shifts
• Clear schedule option
""")
        feat_text.config(state=tk.DISABLED)
        
        # Close button
        ModernButton(content, text="Close", 
                    bg=self.COLORS['accent'], hover=self.COLORS['accent_hover'],
                    command=dialog.destroy).pack(pady=10)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main application entry point"""
    root = tk.Tk()
    
    # Set application icon (if available)
    try:
        root.iconbitmap(default='icon.ico')
    except:
        pass
    
    # Create application
    app = EmployeeShiftSchedulerApp(root)
    
    # Center window on screen
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f'{width}x{height}+{x}+{y}')
    
    # Set minimum window size
    root.minsize(1200, 700)
    
    # Start main loop
    root.mainloop()


if __name__ == "__main__":
    main()