"""Parametric opponent (Patch 19b grid): param_nit_overfolder. Auto-generated thin wrapper."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _param_core import ParametricOpponent

BOT_NAME = "param_nit_overfolder"
_OPP = ParametricOpponent(**{'vpip': 0.12, 'pfr': 0.1, 'threebet_freq': 0.03, 'fold_to_cbet': 0.8, 'aggression_factor': 0.6, 'sizing_profile': 'standard'})

def decide(state):
    return _OPP.decide(state)
