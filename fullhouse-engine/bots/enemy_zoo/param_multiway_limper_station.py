"""Parametric opponent (Patch 19b grid): param_multiway_limper_station. Auto-generated thin wrapper."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _param_core import ParametricOpponent

BOT_NAME = "param_multiway_limper_station"
_OPP = ParametricOpponent(**{'vpip': 0.55, 'pfr': 0.08, 'cbet_freq': 0.25, 'fold_to_cbet': 0.3, 'aggression_factor': 0.6, 'sizing_profile': 'small'})

def decide(state):
    return _OPP.decide(state)
