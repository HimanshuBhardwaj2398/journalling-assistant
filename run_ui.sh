#!/bin/bash
# Quick launcher for the Streamlit Web UI

echo "🧘 Starting Meditation Database Web UI..."
echo ""

# Check if streamlit is installed
if ! poetry run streamlit --version &> /dev/null; then
    echo "⚠️  Streamlit not found. Installing dependencies..."
    poetry lock
    poetry install
    echo ""
fi

# Start the app
echo "✅ Launching Streamlit..."
echo "📱 Opening browser at http://localhost:8501"
echo ""
poetry run streamlit run app.py
