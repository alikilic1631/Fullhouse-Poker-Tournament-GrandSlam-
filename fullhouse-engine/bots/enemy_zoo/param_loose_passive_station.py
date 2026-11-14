"""Parametric opponent (Patch 19b grid): param_loose_passive_station. Auto-generated thin wrapper."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _param_core import ParametricOpponent

BOT_NAME = "param_loose_passive_station"
_OPP = ParametricOpponent(**{'vpip': 0.6, 'pfr': 0.05, 'cbet_freq': 0.2, 'fold_to_cbet': 0.15, 'aggression_factor': 0.3, 'sizing_profile': 'small'})

def decide(state):
    return _OPP.decide(state)
