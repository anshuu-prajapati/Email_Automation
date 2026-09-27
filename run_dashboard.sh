#!/bin/bash
# Start the Streamlit dashboard on Mac/Linux

echo ""
echo "========================================"
echo "  Job Outreach Automation Dashboard"
echo "========================================"
echo ""

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "ERROR: Virtual environment not found!"
    echo "Please run: python3 -m venv venv"
    echo "Then: source venv/bin/activate"
    echo "Then: pip install -r requirements.txt"
    exit 1
fi

# Activate venv
source venv/bin/activate

# Check if streamlit is installed
python -c "import streamlit" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Installing Streamlit..."
    pip install streamlit
fi

# Run streamlit
echo ""
echo "Starting dashboard..."
echo "Open your browser to: http://localhost:8501"
echo ""
echo "Press Ctrl+C to stop the dashboard"
echo ""

streamlit run streamlit_app.py
