#!/usr/bin/env python3
"""Shim for ``pip install -e .`` on older pip (e.g. macOS Command Line Tools Python).

``pyproject.toml`` remains the source of truth; setuptools reads it when this
file calls ``setup()`` with no configuration arguments.
"""
from setuptools import setup

if __name__ == "__main__":
    setup()
