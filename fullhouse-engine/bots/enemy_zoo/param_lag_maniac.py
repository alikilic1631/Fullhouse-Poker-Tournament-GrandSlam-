"""Parametric opponent (Patch 19b grid): param_lag_maniac. Auto-generated thin wrapper."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _param_core import ParametricOpponent

BOT_NAME = "param_lag_maniac"
_OPP = ParametricOpponent(**{'vpip': 0.65, 'pfr': 0.45, 'threebet_freq': 0.18, 'cbet_freq': 0.85, 'fold_to_cbet': 0.25, 'aggression_factor': 4.0, 'sizing_profile': 'overbet', 'river_bluff_freq': 0.3})

def decide(state):
    return _OPP.decide(state)
