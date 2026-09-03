"""Central visual design system for the native POS application."""

from pathlib import Path

COLORS = {
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "nav": "#0F172A",
    "canvas": "#F8FAFC",
    "surface": "#FFFFFF",
    "border": "#E2E8F0",
    "ink": "#0F172A",
    "muted": "#64748B",
    "success": "#16A34A",
    "warning": "#D97706",
    "danger": "#DC2626",
    "info": "#0284C7",
    "nav_muted": "#94A3B8",
    "nav_active": "#1E3A8A",
    "nav_line": "#3B82F6",
}


def load_stylesheet() -> str:
    return Path(__file__).with_name("styles.qss").read_text(encoding="utf-8")


STYLESHEET = load_stylesheet()
