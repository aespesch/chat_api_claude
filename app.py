"""
Streamlit Claude Chat Interface
Python 3.12.7
"""

import os
import streamlit as st
from typing import Optional, List, Dict
from dotenv import load_dotenv
import anthropic
import base64
from io import BytesIO
import time
import warnings

# Suppress Streamlit config warnings
warnings.filterwarnings('ignore')

# Load environment variables from .env file
load_dotenv()

# Page configuration
st.set_page_config(
    page_title="Claude Chat",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS to prevent overlapping elements
st.markdown("""
<style>
    /* Ensure QR code doesn't overlap with instructions */
    .stImage {
        margin-bottom: 30px !important;
        max-width: 300px !important;
    }

    /* Space between QR code and payment instructions */
    div[data-testid="stVerticalBlock"] > div:has(img) {
        margin-bottom: 40px !important;
    }

    /* Payment instructions container */
    .element-container:has(.stMarkdown) {
        clear: both;
        padding-top: 20px;
    }

    /* Ensure proper spacing in columns */
    [data-testid="column"] {
        padding: 10px !important;
        min-height: auto !important;
    }

    /* Fix for QR code container */
    div[data-testid="stImage"] {
        position: relative !important;
        z-index: 1 !important;
    }

    /* Instructions text spacing */
    .stMarkdown {
        margin-top: 20px !important;
    }
</style>
""", unsafe_allow_html=True)

class ClaudeAPI:
    """Class to handle Claude API interactions"""
    
    # Available Claude models (in order of capability)
    MODELS = {
        "claude-opus-4-1-20250805": "Claude Opus 4.1 (Most Advanced)",
        "claude-opus-4-20250701": "Claude Opus 4",
        "claude-sonnet-4-20250701": "Claude Sonnet 4",
        "claude-3-opus-20240229": "Claude 3 Opus",
        "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet",
        "claude-3-sonnet-20240229": "Claude 3 Sonnet",
        "claude-3-haiku-20240307": "Claude 3 Haiku (Fastest)"
    }
    
    def __init__(self):
        """Initialize the Claude API client with API key from .env file"""
        api_key = os.getenv('KEY')
        
        if not api_key:
            raise ValueError("API key not found. Please set KEY in your .env file")
        
        # Initialize the Anthropic client
        self.client = anthropic.Anthropic(api_key=api_key)
    
    def test_model_access(self) -> Dict[str, bool]:
        """Test which models the user has access to"""
        access_results = {}
        
        for model_string in self.MODELS.keys():
            try:
                # Quick test with minimal tokens
                response = self.client.messages.create(
                    model=model_string,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Hi"}]
                )
                access_results[model_string] = True
            except:
                access_results[model_string] = False
        
        return access_results
    
    def send_message(
        self,
        message: str,
        model: str,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        system: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
        files: Optional[List] = None
    ) -> str:
        """
        Send a message to Claude and get response
        
        Args:
            message: The user message to send
            model: Model string to use
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (0-1)
            system: Optional system prompt
            conversation_history: Optional previous messages for context
            files: Optional list of uploaded files
            
        Returns:
            Claude's response as string
        """
        try:
            # Build messages list
            messages = conversation_history if conversation_history else []
            
            # Prepare message content
            content = []
            
            # Add text message
            content.append({
                "type": "text",
                "text": message
            })
            
            # Add files if provided
            if files:
                for file in files:
                    if file.type and file.type.startswith('image/'):
                        # Read and encode image
                        image_data = file.read()
                        base64_image = base64.b64encode(image_data).decode('utf-8')
                        
                        content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": file.type,
                                "data": base64_image
                            }
                        })
                    elif file.name.endswith(('.txt', '.py', '.csv', '.md', '.json', '.xml', '.yaml', '.yml')):
                        # Read text-based files
                        try:
                            text_content = file.read().decode('utf-8')
                            file_type = "Python code" if file.name.endswith('.py') else "file"
                            content.append({
                                "type": "text",
                                "text": f"\n\n{file_type} content ({file.name}):\n```{'python' if file.name.endswith('.py') else ''}\n{text_content}\n```"
                            })
                        except Exception as e:
                            content.append({
                                "type": "text",
                                "text": f"\n\nError reading file {file.name}: {str(e)}"
                            })
            
            # Add message with content
            messages.append({"role": "user", "content": content})
            
            # Create the request parameters
            params = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages
            }
            
            # Add system prompt if provided
            if system:
                params["system"] = system
            
            # Send request to Claude
            response = self.client.messages.create(**params)
            
            # Extract and return the text response
            return response.content[0].text
            
        except anthropic.PermissionDeniedError:
            return f"❌ Permission denied for this model. Please check your API plan."
        except anthropic.APIError as e:
            return f"❌ API Error: {str(e)}"
        except Exception as e:
            return f"❌ Unexpected error: {str(e)}"


def initialize_session_state():
    """Initialize Streamlit session state variables"""
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    
    if 'available_models' not in st.session_state:
        st.session_state.available_models = {}
    
    if 'models_tested' not in st.session_state:
        st.session_state.models_tested = False
    
    if 'claude_api' not in st.session_state:
        try:
            st.session_state.claude_api = ClaudeAPI()
        except ValueError as e:
            st.error(f"⚠️ {str(e)}")
            st.stop()


def test_available_models():
    """Test and cache available models"""
    if not st.session_state.models_tested:
        with st.spinner("Testing available models..."):
            access_results = st.session_state.claude_api.test_model_access()
            st.session_state.available_models = {
                model: name for model, name in ClaudeAPI.MODELS.items() 
                if access_results.get(model, False)
            }
            st.session_state.models_tested = True


def render_sidebar():
    """Render the sidebar with settings"""
    with st.sidebar:
        st.title("⚙️ Settings")
        
        # Model selection
        st.subheader("Model Selection")
        
        if st.session_state.available_models:
            # Get the best available model as default
            default_model = list(st.session_state.available_models.keys())[0]
            
            selected_model = st.selectbox(
                "Choose Model",
                options=list(st.session_state.available_models.keys()),
                format_func=lambda x: st.session_state.available_models[x],
                index=0,
                help="Select the Claude model to use for responses"
            )
        else:
            st.error("No models available. Please check your API key.")
            selected_model = None
        
        # Temperature slider
        temperature = st.slider(
            "Temperature",
            min_value=0.0,
            max_value=1.0,
            value=0.7,
            step=0.1,
            help="Higher values make the output more random"
        )
        
        # Max tokens
        max_tokens = st.slider(
            "Max Tokens",
            min_value=100,
            max_value=4000,
            value=2000,
            step=100,
            help="Maximum length of the response"
        )
        
        # System prompt
        system_prompt = st.text_area(
            "System Prompt (Optional)",
            placeholder="Set a system prompt to guide Claude's behavior...",
            help="Optional instructions that Claude will follow"
        )
        
        st.divider()
        
        # Clear conversation button
        if st.button("🗑️ Clear Conversation", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
        
        # Model info
        st.divider()
        st.subheader("📊 Model Status")
        
        if st.session_state.available_models:
            st.success(f"✅ {len(st.session_state.available_models)} models available")
            
            with st.expander("View Available Models"):
                for model, name in st.session_state.available_models.items():
                    st.write(f"• {name}")
        else:
            st.warning("⚠️ No models available")
        
        return selected_model, temperature, max_tokens, system_prompt


def render_chat_interface(model, temperature, max_tokens, system_prompt):
    """Render the main chat interface"""
    st.title("🤖 Claude Chat Interface")
    
    # Show welcome message if no messages
    if not st.session_state.messages:
        st.markdown("""
        ### Welcome to Claude Chat! 👋
        
        I'm ready to help you with:
        - 💡 Answering questions
        - 📝 Writing and editing content
        - 🔍 Analysis and research
        - 💻 Coding assistance
        - 🎨 Creative projects
        
        **Start by typing a message below!**
        """)
    
    # Message container
    messages_container = st.container()
    
    # Display chat messages
    with messages_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # Add spacing to prevent overlap
    st.markdown("<div style='margin-top: 30px; margin-bottom: 20px;'></div>", unsafe_allow_html=True)
    
    # File upload section (outside the chat input for better UX)
    with st.expander("📎 Attach Files (Optional)", expanded=False):
        uploaded_files = st.file_uploader(
            "Upload files to include with your next message",
            accept_multiple_files=True,
            type=['png', 'jpg', 'jpeg', 'gif', 'txt', 'py', 'csv', 'md', 'json', 'xml', 'yaml', 'yml'],
            help="Supported: Images (PNG, JPG, JPEG, GIF), Code (PY), and Text files (TXT, CSV, MD, JSON, XML, YAML)",
            key="file_uploader"
        )
        if uploaded_files:
            st.info(f"📎 {len(uploaded_files)} file(s) ready to send with next message")
            # Show file names
            for file in uploaded_files:
                st.caption(f"• {file.name}")

    st.markdown("<div style='clear: both; margin-bottom: 30px;'></div>", unsafe_allow_html=True)
    
    # Chat input using Streamlit's chat_input (prevents loops)
    if prompt := st.chat_input("Type your message here...", key="chat_input"):
        if model:
            # Add user message to history
            st.session_state.messages.append({"role": "user", "content": prompt})
            
            # Display user message immediately
            with messages_container:
                with st.chat_message("user"):
                    st.markdown(prompt)
                    if uploaded_files:
                        st.caption(f"📎 Attached {len(uploaded_files)} file(s)")
                
                # Generate and display Claude's response
                with st.chat_message("assistant"):
                    message_placeholder = st.empty()
                    
                    # Show thinking animation
                    with message_placeholder.container():
                        with st.spinner("Claude is thinking..."):
                            # Prepare conversation history
                            conversation_history = [
                                {"role": msg["role"], "content": msg["content"]} 
                                for msg in st.session_state.messages[:-1]
                            ]
                            
                            # Get response from Claude
                            response = st.session_state.claude_api.send_message(
                                message=prompt,
                                model=model,
                                max_tokens=max_tokens,
                                temperature=temperature,
                                system=system_prompt if system_prompt else None,
                                conversation_history=conversation_history,
                                files=uploaded_files
                            )
                    
                    # Display the actual response
                    message_placeholder.markdown(response)
                    
                    # Add assistant response to history
                    st.session_state.messages.append({"role": "assistant", "content": response})
            
            # Clear uploaded files after sending (trigger rerun)
            if uploaded_files:
                time.sleep(0.5)  # Small delay to ensure message is displayed
                st.rerun()
        else:
            st.error("⚠️ Please select a model from the sidebar")


def create_config_file():
    """Create a Streamlit config file to prevent deprecated config warnings"""
    config_dir = os.path.expanduser("~/.streamlit")
    config_file = os.path.join(config_dir, "config.toml")
    
    # Create directory if it doesn't exist
    os.makedirs(config_dir, exist_ok=True)
    
    # Basic config to prevent warnings
    config_content = """[server]
headless = true

[browser]
gatherUsageStats = false

[theme]
base = "dark"
"""
    
    # Only create if doesn't exist or is using old configs
    if not os.path.exists(config_file):
        with open(config_file, 'w') as f:
            f.write(config_content)
    else:
        # Read existing config and remove deprecated options
        with open(config_file, 'r') as f:
            lines = f.readlines()
        
        # Filter out deprecated options
        deprecated = ['runner.installTracer', 'client.caching', 'client.displayEnabled']
        filtered_lines = []
        skip_next = False
        
        for line in lines:
            if skip_next:
                skip_next = False
                continue
                
            if any(dep in line for dep in deprecated):
                skip_next = True
                continue
                
            filtered_lines.append(line)
        
        # Write back filtered config
        with open(config_file, 'w') as f:
            f.writelines(filtered_lines)


def main():
    """Main application function"""
    # Clean up deprecated config options
    try:
        create_config_file()
    except:
        pass  # Ignore config file errors
    
    # Initialize session state
    initialize_session_state()
    
    # Test available models
    test_available_models()
    
    # Render sidebar and get settings
    model, temperature, max_tokens, system_prompt = render_sidebar()
    
    # Render main chat interface
    if model:
        render_chat_interface(model, temperature, max_tokens, system_prompt)
    else:
        st.error("❌ No models available. Please check your API key and subscription.")
        st.info("""
        ### Setup Instructions:
        1. Make sure you have a `.env` file with your API key: `KEY=your-api-key`
        2. Check your Anthropic account has access to Claude models
        3. Visit https://console.anthropic.com to manage your subscription
        """)


if __name__ == "__main__":
    main()