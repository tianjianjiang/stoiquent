#!/usr/bin/env python3
"""Greet someone by name."""
import sys
import json

if len(sys.argv) > 1:
    args = json.loads(sys.argv[1])
    name = args.get("name", "World")
else:
    name = "World"

print(f"Hello, {name}!")
