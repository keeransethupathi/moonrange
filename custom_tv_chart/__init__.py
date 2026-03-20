import os
import streamlit.components.v1 as components

parent_dir = os.path.dirname(os.path.abspath(__file__))
build_dir = os.path.join(parent_dir, "frontend")
_tv_chart = components.declare_component("tv_chart", path=build_dir)

def renderCustomLightweightCharts(chartOptionsArgs, key=None):
    return _tv_chart(chartOptionsArgs=chartOptionsArgs, key=key)
