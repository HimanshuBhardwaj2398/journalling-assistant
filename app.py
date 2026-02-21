#!/usr/bin/env python3
"""
Meditation Database - Web Interface

Simple Streamlit app for ingesting and exploring meditation texts.

Usage:
    streamlit run app.py
"""

import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from views import ingest, queue, browse, stats

# Page configuration
st.set_page_config(
    page_title="Meditation Database",
    page_icon="~",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Session state initialization
if "ingestion_result" not in st.session_state:
    st.session_state.ingestion_result = None

if "processing_status" not in st.session_state:
    st.session_state.processing_status = {}

if "last_processed_id" not in st.session_state:
    st.session_state.last_processed_id = None

# Sidebar navigation
with st.sidebar:
    st.title("Meditation Database")
    st.markdown("---")

    page = st.radio(
        "Navigation",
        ["Ingest New Document", "Processing Queue", "Browse Database", "Statistics"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.caption("Built with Streamlit + LangChain + Voyage AI")

# Page routing
if page == "Ingest New Document":
    ingest.render()
elif page == "Processing Queue":
    queue.render()
elif page == "Browse Database":
    browse.render()
elif page == "Statistics":
    stats.render()
