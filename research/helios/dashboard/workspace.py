"""Compatibility entry points for the research workstation."""

from helios.dashboard.workstation_shell import PAGES, STYLE, navigate, render_shell

__all__ = ["PAGES", "STYLE", "navigate", "render_shell", "render_datasets"]


def render_datasets() -> None:
    from helios.dashboard.datasets_page import render_datasets as render_inventory

    render_inventory()
