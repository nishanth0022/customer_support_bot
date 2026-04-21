# app/monitoring/__init__.py
from .logger import log_event, get_all_events, event_count

__all__ = ["log_event", "get_all_events", "event_count"]
