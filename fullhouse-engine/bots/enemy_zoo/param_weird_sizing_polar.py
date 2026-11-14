"""Parametric opponent (Patch 19b grid): param_weird_sizing_polar. Auto-generated thin wrapper."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _param_core import ParametricOpponent

BOT_NAME = "param_weird_sizing_polar"
_OPP = ParametricOpponent(**{'vpip': 0.22, 'pfr': 0.18, 'cbet_freq': 0.6, 'fold_to_cbet': 0.55, 'aggression_factor': 2.8, 'sizing_profile': 'overbet', 'river_bluff_freq': 0.3})

def decide(state):
    return _OPP.decide(state)
