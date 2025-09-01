#!/bin/bash
# Script to run the Claude Chat Streamlit application

echo "🚀 Starting Claude Chat Interface..."
echo "=================================="

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found!"
    echo "Please create a .env file with your API key:"
    echo "KEY=your-anthropic-api-key-here"
    exit 1
fi

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "✅ Activating virtual environment..."
    source venv/bin/activate
else
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
fi

# Install dependencies
echo "📚 Installing dependencies..."
pip install -q -r requirements.txt

# Create .streamlit directory if it doesn't exist
if [ ! -d ".streamlit" ]; then
    echo "📁 Creating .streamlit configuration directory..."
    mkdir .streamlit
fi

# Run the Streamlit app
echo "=================================="
echo "🎉 Launching Streamlit app..."
echo "📍 Opening at: http://localhost:8501"
echo "Press Ctrl+C to stop the server"
echo "=================================="

streamlit run app.py