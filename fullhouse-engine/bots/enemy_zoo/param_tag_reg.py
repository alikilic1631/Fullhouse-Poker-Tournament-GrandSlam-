"""Parametric opponent (Patch 19b grid): param_tag_reg. Auto-generated thin wrapper."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _param_core import ParametricOpponent

BOT_NAME = "param_tag_reg"
_OPP = ParametricOpponent(**{'vpip': 0.22, 'pfr': 0.18, 'threebet_freq': 0.08, 'cbet_freq': 0.7, 'fold_to_cbet': 0.55, 'aggression_factor': 2.5, 'sizing_profile': 'standard'})

def decide(state):
    return _OPP.decide(state)
