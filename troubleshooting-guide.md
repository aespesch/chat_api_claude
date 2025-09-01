# Troubleshooting Guide - Claude Chat Streamlit

## Common Issues and Solutions

### 🔄 Problem: Messages Being Sent Multiple Times (Loop)

**Symptoms:**
- The same message is sent repeatedly
- Chat interface keeps refreshing
- Multiple identical responses appear

**Solution:**
The latest version of the code uses `st.chat_input()` which prevents this issue. If you're still experiencing loops:

1. **Update Streamlit:**
```bash
pip install --upgrade streamlit
```

2. **Clear Browser Cache:**
- Chrome/Edge: Ctrl+Shift+Delete
- Firefox: Ctrl+Shift+Delete
- Safari: Cmd+Shift+Delete

3. **Restart the Application:**
```bash
# Stop with Ctrl+C, then restart:
streamlit run app.py
```

### ❌ Problem: No Models Available

**Symptoms:**
- "No models available" error
- Empty model dropdown

**Solutions:**

1. **Check API Key:**
```bash
# Verify .env file exists and contains:
cat .env
# Should show: KEY=sk-ant-api03-...
```

2. **Test API Key Directly:**
```python
# Test script (save as test_api.py)
import os
from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv('KEY'))

try:
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=10,
        messages=[{"role": "user", "content": "Hi"}]
    )
    print("✅ API Key is working!")
except Exception as e:
    print(f"❌ Error: {e}")
```

3. **Check Account Status:**
- Visit: https://console.anthropic.com
- Verify your subscription is active
- Check if you have API credits

### 🐌 Problem: Slow Response Times

**Solutions:**

1. **Use a Faster Model:**
- Switch to Claude Haiku for faster responses
- Reduce Max Tokens in settings

2. **Check Internet Connection:**
```bash
# Test connection to Anthropic
ping api.anthropic.com
```

3. **Optimize Settings:**
- Lower the Max Tokens value
- Reduce Temperature for more focused responses

### 📎 Problem: File Upload Not Working

**Symptoms:**
- Files don't attach
- Error when uploading files
- Files disappear after upload

**Solutions:**

1. **Check File Size:**
- Maximum file size: 25MB (configurable)
- Reduce image resolution if needed

2. **Supported Formats:**
- Images: PNG, JPG, JPEG, GIF only
- Text: TXT, CSV only
- PDFs: Text extraction only

3. **Clear and Re-upload:**
- Click "Clear Conversation"
- Upload file first, then type message

### 💾 Problem: Conversation History Lost

**Symptoms:**
- Messages disappear on refresh
- Can't see previous conversations

**Note:** This is expected behavior. Streamlit doesn't persist data between sessions.

**Workarounds:**

1. **Export Conversation (Manual):**
- Select all text (Ctrl+A)
- Copy and save to a document

2. **Add Persistence (Advanced):**
```python
# Add to app.py for database persistence
import sqlite3

def save_message(role, content):
    conn = sqlite3.connect('chat_history.db')
    # ... implementation
```

### 🚫 Problem: Permission Denied Errors

**Symptoms:**
- "Permission denied for this model"
- "Upgrade required" messages

**Solutions:**

1. **Check Your Plan:**
- Visit: https://console.anthropic.com
- Verify which models your plan includes

2. **Use Available Models:**
- The app automatically detects available models
- Select a different model from the dropdown

### 🔧 Problem: Streamlit Won't Start

**Error Messages and Solutions:**

1. **"Module not found":**
```bash
pip install -r requirements.txt
```

2. **"Port already in use":**
```bash
# Use different port
streamlit run app.py --server.port 8502
```

3. **"Command not found":**
```bash
# Reinstall Streamlit
pip uninstall streamlit
pip install streamlit
```

### 🔑 Problem: API Key Not Found

**Error:** "API key not found. Please set KEY in your .env file"

**Solutions:**

1. **Create .env File:**
```bash
# In the same directory as app.py
echo "KEY=your-api-key-here" > .env
```

2. **Check File Location:**
```bash
# .env must be in same directory as app.py
ls -la | grep -E "(app.py|.env)"
```

3. **Remove Quotes from Key:**
```
# Correct:
KEY=sk-ant-api03-xxxxx

# Wrong:
KEY="sk-ant-api03-xxxxx"
```

### 📱 Problem: Mobile Display Issues

**Solutions:**

1. **Use Responsive Mode:**
- The interface should adapt automatically
- Try landscape orientation for better experience

2. **Zoom Adjustments:**
- Pinch to zoom if text is too small
- Double-tap to fit screen

## Quick Fixes Checklist

If something isn't working, try these in order:

1. ✅ Refresh the browser page (F5)
2. ✅ Clear browser cache
3. ✅ Restart Streamlit (Ctrl+C, then `streamlit run app.py`)
4. ✅ Update dependencies (`pip install -r requirements.txt --upgrade`)
5. ✅ Check .env file exists and has valid API key
6. ✅ Try a different browser
7. ✅ Check Anthropic service status

## Still Having Issues?

1. **Check Logs:**
```bash
streamlit run app.py --logger.level=debug
```

2. **Get Help:**
- Anthropic Support: https://support.anthropic.com
- Streamlit Forums: https://discuss.streamlit.io
- Check API Status: https://status.anthropic.com

## Prevention Tips

1. **Keep Software Updated:**
```bash
# Monthly update routine
pip install --upgrade streamlit anthropic python-dotenv
```

2. **Monitor API Usage:**
- Check dashboard regularly: https://console.anthropic.com
- Set up usage alerts if available

3. **Test After Changes:**
- Always test after updating code
- Keep a backup of working configuration