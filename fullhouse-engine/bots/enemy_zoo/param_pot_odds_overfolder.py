"""Parametric opponent (Patch 19b grid): param_pot_odds_overfolder. Auto-generated thin wrapper."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _param_core import ParametricOpponent

BOT_NAME = "param_pot_odds_overfolder"
_OPP = ParametricOpponent(**{'vpip': 0.18, 'pfr': 0.12, 'fold_to_cbet': 0.7, 'aggression_factor': 0.8, 'sizing_profile': 'standard'})

def decide(state):
    return _OPP.decide(state)
