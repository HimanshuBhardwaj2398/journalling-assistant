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

from views import (  # noqa: E402
    agent_playground,
    browse,
    ingest,
    queue,
    rag_playground,
    stats,
    validation,
)

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

if "nav_page" not in st.session_state:
    st.session_state.nav_page = "Ingest New Document"

# Sidebar navigation
with st.sidebar:
    st.title("Meditation Database")
    st.markdown("---")

    page = st.radio(
        "Navigation",
        [
            "Ingest New Document",
            "Processing Queue",
            "Browse Database",
            "RAG Playground",
            "Agent Playground",
            "Statistics",
            "Validation",
        ],
        label_visibility="collapsed",
        key="nav_page",
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
elif page == "RAG Playground":
    rag_playground.render()
elif page == "Agent Playground":
    agent_playground.render()
elif page == "Statistics":
    stats.render()
elif page == "Validation":
    validation.render()
