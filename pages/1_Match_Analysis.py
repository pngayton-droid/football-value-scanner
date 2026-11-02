
from pathlib import Path
import runpy

report_file = Path(__file__).resolve().parent.parent / "match_report (1).py"

if report_file.exists():
    runpy.run_path(str(report_file), run_name="__main__")
else:
    import streamlit as st
    st.error("Match report file not found.")

