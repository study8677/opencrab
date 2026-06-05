#!/usr/bin/env python3
"""Bootstrap and run the fitness ledger."""
import sys
import os

# Ensure we can import modules
sys.path.insert(0, os.path.dirname(__file__))

# Import and run
from run_now import run
run()
