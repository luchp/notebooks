# -*- coding: utf-8 -*-
"""
Created on Mon Feb 22 13:24:49 2016

@author: Luc
"""
import time
import matplotlib.legend as mlegend



def gridsetup(ax):
    """Display a mayor and minor grid with subdued colors"""
    if hasattr(ax, "tolist"):
        ax = ax.tolist()  # matplotlib return a numpy array from subplots
    axis = ax if isinstance(ax, (list, tuple)) else [ax]
    for a in axis:
        a.grid(visible=True, which="major", color="0.6", linestyle="-")
        a.grid(visible=True, which="minor", color="0.7", linestyle="-")
        a.minorticks_on()

