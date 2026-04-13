"""Minimal NiceGUI entry point for testing.

The testing framework requires ui.run() at module level.
Tests register their own @ui.page routes.
"""
from nicegui import ui

ui.run(reload=False)
