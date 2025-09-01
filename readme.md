# Claude Chat - Streamlit Interface

A modern web interface for chatting with Claude using Streamlit.

## Features

- 🤖 **Multi-Model Support**: Automatically detects and lists available Claude models
- 📎 **File Upload**: Attach images and text files to your messages
- 💬 **Conversation History**: Maintains chat context throughout the session
- ⚙️ **Customizable Settings**: Adjust temperature, max tokens, and system prompts
- 🎨 **Modern UI**: Clean and responsive interface
- ✅ **Auto Model Detection**: Only shows models you have access to

## Installation

### 1. Clone or Download the Files

Ensure you have these files in the same directory:
- `app.py` (the main Streamlit application)
- `.env` (your API key configuration)
- `requirements.txt` (Python dependencies)

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure API Key

Create a `.env` file in the same directory with your Anthropic API key:

```
KEY=sk-ant-api03-your-actual-api-key-here
```

⚠️ **Important**: Never commit your `.env` file to version control!

## Running the Application

### Standard Method

```bash
streamlit run app.py
```

### With Custom Port

```bash
streamlit run app.py --server.port 8080
```

### For Network Access

```bash
streamlit run app.py --server.address 0.0.0.0
```

## Usage Guide

### 1. **Model Selection**
- The app automatically tests which models you have access to
- Select your preferred model from the sidebar dropdown
- Only accessible models are shown

### 2. **Sending Messages**
- Type your message in the text input field
- Press "Send" or hit Enter to submit
- Optionally attach files using the file uploader

### 3. **File Attachments**
Supported file types:
- **Images**: PNG, JPG, JPEG, GIF
- **Text**: TXT, CSV
- **Documents**: PDF (text extraction)

### 4. **Customization Options**
- **Temperature** (0.0-1.0): Controls response creativity
- **Max Tokens**: Limits response length
- **System Prompt**: Set custom instructions for Claude

### 5. **Managing Conversations**
- Click "Clear Conversation" to start fresh
- Chat history is maintained during the session
- History is lost when you close the browser

## Troubleshooting

### No Models Available

If you see "No models available":
1. Check your API key in the `.env` file
2. Verify your Anthropic account subscription
3. Visit https://console.anthropic.com to check your plan

### API Errors

Common issues and solutions:
- **Permission Denied**: Upgrade your API plan for advanced models
- **Rate Limit**: Wait a moment and try again
- **Invalid API Key**: Double-check your `.env` file

### Streamlit Issues

If Streamlit doesn't start:
```bash
# Update Streamlit
pip install --upgrade streamlit

# Clear cache
streamlit cache clear

# Run with debugging
streamlit run app.py --logger.level=debug
```

## Model Information

The app supports these Claude models (if you have access):
- **Claude Opus 4.1**: Most advanced (August 2025)
- **Claude Opus 4**: Previous Opus version
- **Claude Sonnet 4**: Balanced performance
- **Claude 3 Opus**: Older but capable
- **Claude 3.5 Sonnet**: Updated Sonnet
- **Claude 3 Sonnet**: Balanced older model
- **Claude 3 Haiku**: Fast and efficient

## Security Best Practices

1. **Protect Your API Key**
   - Never share your API key
   - Add `.env` to `.gitignore`
   - Use environment variables in production

2. **File Upload Safety**
   - The app processes files locally
   - Files are not permanently stored
   - Be cautious with sensitive documents

## Support

- **API Documentation**: https://docs.anthropic.com
- **Anthropic Support**: https://support.anthropic.com
- **Streamlit Documentation**: https://docs.streamlit.io

## License

This application is for educational and development purposes. Ensure you comply with Anthropic's terms of service when using their API."# chat_api_claude" 
