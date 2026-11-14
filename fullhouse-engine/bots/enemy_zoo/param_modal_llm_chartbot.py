"""Parametric opponent (Patch 19b grid): param_modal_llm_chartbot. Auto-generated thin wrapper."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _param_core import ParametricOpponent

BOT_NAME = "param_modal_llm_chartbot"
_OPP = ParametricOpponent(**{'vpip': 0.25, 'pfr': 0.2, 'threebet_freq': 0.07, 'cbet_freq': 0.7, 'fold_to_cbet': 0.55, 'aggression_factor': 2.0, 'sizing_profile': 'standard'})

def decide(state):
    return _OPP.decide(state)
