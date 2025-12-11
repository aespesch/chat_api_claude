import os, streamlit as st, anthropic, base64, warnings, re, json, html, io, hashlib
from pathlib import Path
from streamlit.components.v1 import html as st_html
from datetime import datetime
import PyPDF2
warnings.filterwarnings('ignore')
st.set_page_config(page_title="Claude Chat", page_icon="🤖", layout="wide")

class APIError(Exception):
    """Custom API error class"""
    pass

class ClaudeAPI:
    MODELS = {
        "claude-opus-4-5-20251101": "Claude Opus 4.5 (Most Advanced and Intelligent)",
        "claude-sonnet-4-5-20250929": "Claude Sonnet 4.5 (Smarter for Agents and Coding)",
        "claude-haiku-4-5-20251001": "Claude Haiku 4.5 (Fastest, Near-Frontier Intelligence)",
        "claude-opus-4-1-20250805": "Claude Opus 4.1 (Exceptional for Specialized Reasoning)",
        "claude-sonnet-4-20250514": "Claude Sonnet 4 (Legacy)",
        "claude-3-7-sonnet-20250219": "Claude 3.7 Sonnet (Legacy)",
        "claude-opus-4-20250514": "Claude Opus 4 (Legacy)",
        "claude-3-5-haiku-20241022": "Claude 3.5 Haiku (Legacy)",
        "claude-3-haiku-20240307": "Claude 3 Haiku (Legacy)",
    }

    MODEL_MAX_TOKENS = {
        "claude-opus-4-5-20251101": 64000,
        "claude-sonnet-4-5-20250929": 64000,
        "claude-haiku-4-5-20251001": 64000,
        "claude-opus-4-1-20250805": 32000,
        "claude-sonnet-4-20250514": 64000,
        "claude-opus-4-20250514": 32000,
        "claude-3-7-sonnet-20250219": 131072,
        "claude-3-5-haiku-20241022": 8192,
        "claude-3-haiku-20240307": 4096,
    }

    PROMPT_TEMPLATES = {
        "Code Review": "Analyze this code and suggest improvements:",
        "Summary": "Create an executive summary of the following text:",
        "Translation": "Translate the following text to {language}:",
        "Debug": "Find and fix errors in this code:",
        "Explain": "Explain this concept in simple terms:",
        "Refactor": "Refactor this code for better performance and readability:",
    }

    @classmethod
    def get_max_tokens(cls, model):
        """Returns maximum token limit for a specific model"""
        return cls.MODEL_MAX_TOKENS.get(model, 4000)

    def __init__(self):
        self.client = None
        self.api_key = self._get_api_key()

        if self.api_key:
            try:
                self.client = anthropic.Anthropic(api_key=self.api_key)
                if not self._validate_api_key():
                    st.error("❌ Invalid API key!")
                    self.client = None
            except Exception as e:
                st.error(f"❌ Error initializing API: {str(e)}")
                self.client = None
        else:
            st.error("❌ API key not found!")

    def _get_api_key(self):
        """Get API key from various sources"""
        if hasattr(st, 'secrets') and len(st.secrets) > 0:
            try:
                return st.secrets.get("KEY")
            except:
                pass

        api_key = os.getenv("KEY")
        if api_key:
            return api_key

        try:
            import toml
            secrets_path = Path(__file__).parent / ".streamlit" / "secrets.toml"
            if secrets_path.exists():
                secrets = toml.load(secrets_path)
                return secrets.get("KEY")
        except:
            pass

        return None

    def _validate_api_key(self):
        """Validate API key with minimal call"""
        try:
            self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1,
                messages=[{"role": "user", "content": "Hi"}]
            )
            return True
        except:
            return False

    def send_message_stream(self, msg, model, temp=0.7, max_t=2000, hist=None, files=None, system_prompt=None):
        """Stream version that returns a generator"""
        if not self.client: 
            yield "❌ API key not configured"
            return

        content = [{"type": "text", "text": sanitize_input(msg)}]

        if files:
            for f in files:
                f.seek(0)
                try:
                    processed_content = process_file(f)
                    if processed_content:
                        content.append(processed_content)
                except Exception as e:
                    st.warning(f"Could not process file {f.name}: {e}")

        msgs = (hist or []) + [{"role": "user", "content": content}]

        kwargs = {
            "model": model,
            "max_tokens": max_t,
            "temperature": temp,
            "messages": msgs
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        try:
            with self.client.messages.stream(**kwargs) as stream:
                for text in stream.text_stream:
                    yield text
        except anthropic.RateLimitError:
            yield "⏱️ Rate limit reached. Please wait a few seconds..."
        except anthropic.AuthenticationError:
            yield "🔐 Authentication error. Please check your API key."
        except anthropic.BadRequestError as e:
            if "model" in str(e).lower():
                yield f"❌ Model '{model}' not available"
            else:
                yield f"❌ Invalid request: {str(e)}"
        except Exception as e:
            yield f"❌ Unexpected error: {str(e)}"

@st.cache_data(ttl=3600)
def extract_text_from_pdf_cached(pdf_content):
    """Cached version of PDF extraction"""
    pdf_file = io.BytesIO(pdf_content)
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    for page_num, page in enumerate(pdf_reader.pages, 1):
        text += f"\n--- Page {page_num} ---\n{page.extract_text()}\n"
    return text

def sanitize_input(text):
    """Sanitize user input"""
    return html.escape(text)

def validate_file(file):
    """Validate file before processing"""
    MAX_SIZE = 10 * 1024 * 1024

    if file.size > MAX_SIZE:
        raise ValueError(f"File too large: {file.size/1024/1024:.1f}MB")

    return True

FILE_PROCESSORS = {
    '.pdf': lambda f: {"type": "text", "text": f"\n📄 {f.name} (PDF):\n```\n{extract_text_from_pdf_cached(f.read())}\n```"},
    '.xlsx': lambda f: {"type": "text", "text": f"\n📄 {f.name}: Excel file processing not implemented\n"},
    '.docx': lambda f: {"type": "text", "text": f"\n📄 {f.name}: Word file processing not implemented\n"},
    '.ipynb': lambda f: {"type": "text", "text": f"\n📄 {f.name}: Jupyter notebook processing not implemented\n"},
    '.zip': lambda f: {"type": "text", "text": f"\n📄 {f.name}: ZIP file processing not implemented\n"},
}

def process_file(file):
    """Universal file processor"""
    validate_file(file)
    extension = Path(file.name).suffix.lower()
    fname = file.name.lower()

    if file.type.startswith('image/'):
        file.seek(0)
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": file.type,
                "data": base64.b64encode(file.read()).decode()
            }
        }

    if extension in FILE_PROCESSORS:
        file.seek(0)
        return FILE_PROCESSORS[extension](file)

    text_extensions = ['.txt','.py','.csv','.md','.json','.php','.cfg','.sql','.js','.html','.css','.xml','.yml','.yaml']
    if extension in text_extensions:
        file.seek(0)
        text_content = file.read().decode('utf-8', errors='ignore')
        lang_map = {
            '.php': 'php', '.sql': 'sql', '.py': 'python',
            '.json': 'json', '.js': 'javascript', '.html': 'html',
            '.css': 'css', '.xml': 'xml', '.yml': 'yaml', '.yaml': 'yaml'
        }
        lang = lang_map.get(extension, '')
        return {"type": "text", "text": f"\n📄 {file.name}:\n```{lang}\n{text_content}\n```"}

    return None

def estimate_tokens(text):
    """Estimate token count"""
    return len(text) // 4

def extract_mermaid_diagrams(text):
    """Extract all Mermaid diagrams from text"""
    pattern = r'```mermaid\s*\n(.*?)```'
    matches = re.findall(pattern, text, re.DOTALL)
    return matches

def render_mermaid(mermaid_code, key=None):
    """Render Mermaid diagram using HTML and JavaScript"""
    mermaid_code_escaped = mermaid_code.replace('`', '\\`').replace('$', '\\$')

    mermaid_html = f"""
    <div class="mermaid-container" style="background: white; padding: 20px; border-radius: 8px; margin: 10px 0;">
        <div class="mermaid">
{mermaid_code}
        </div>
    </div>

    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ 
            startOnLoad: true,
            theme: 'default',
            securityLevel: 'loose',
            flowchart: {{
                useMaxWidth: true,
                htmlLabels: true,
                curve: 'basis'
            }}
        }});
    </script>
    """

    st_html(mermaid_html, height=400, scrolling=True)

def render_message_with_mermaid(content):
    """Render message, processing Mermaid diagrams separately"""
    mermaid_diagrams = extract_mermaid_diagrams(content)

    if not mermaid_diagrams:
        st.markdown(content)
        return

    parts = re.split(r'```mermaid\s*\n.*?```', content, flags=re.DOTALL)

    for i, part in enumerate(parts):
        if part.strip():
            st.markdown(part)

        if i < len(mermaid_diagrams):
            st.markdown("**📊 Diagram:**")
            render_mermaid(mermaid_diagrams[i], key=f"mermaid_{i}_{hash(content)}")

def display_message_with_metadata(message, idx):
    """Display message with useful metadata"""
    col1, col2, col3 = st.columns([8, 1, 1])

    with col1:
        render_message_with_mermaid(message['content'])

    with col2:
        token_count = estimate_tokens(message['content'])
        st.caption(f"🔤 {token_count}")

    with col3:
        if st.button("📋", key=f"copy_{idx}", help="Copy"):
            st.code(message['content'])

def save_conversation():
    """Save current conversation"""
    if not st.session_state.msgs:
        st.warning("No messages to save")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"chat_{timestamp}.json"

    conversation_data = {
        "timestamp": timestamp,
        "messages": st.session_state.msgs,
        "model": st.session_state.selected_model
    }

    if 'saved_conversations' not in st.session_state:
        st.session_state.saved_conversations = {}

    st.session_state.saved_conversations[filename] = conversation_data
    st.success(f"Conversation saved as {filename}")

def load_conversation(filename):
    """Load saved conversation"""
    if filename in st.session_state.saved_conversations:
        data = st.session_state.saved_conversations[filename]
        st.session_state.msgs = data["messages"]
        st.session_state.selected_model = data.get("model", list(ClaudeAPI.MODELS.keys())[0])
        st.success("Conversation loaded")
        st.rerun()

def list_saved_conversations():
    """List all saved conversations"""
    if 'saved_conversations' in st.session_state:
        return list(st.session_state.saved_conversations.keys())
    return []

def export_conversation(format_type="Markdown"):
    """Export conversation in different formats"""
    if not st.session_state.msgs:
        return None

    if format_type == "Markdown":
        content = "# Chat Export\n\n"
        for msg in st.session_state.msgs:
            role = msg['role'].capitalize()
            content += f"## {role}\n\n{msg['content']}\n\n---\n\n"
        return content
    elif format_type == "JSON":
        return json.dumps(st.session_state.msgs, indent=2)

    return None

def create_usage_dataframe(messages):
    """Create usage statistics dataframe"""
    import pandas as pd

    data = []
    total_tokens = 0
    for i, msg in enumerate(messages):
        tokens = estimate_tokens(msg['content'])
        total_tokens += tokens
        data.append({
            'Message': i + 1,
            'Role': msg['role'],
            'Tokens': tokens,
            'Cumulative': total_tokens
        })

    return pd.DataFrame(data)

# Initialize session state
if 'msgs' not in st.session_state: 
    st.session_state.msgs = []
if 'api' not in st.session_state: 
    st.session_state.api = ClaudeAPI()
if 'selected_model' not in st.session_state:
    st.session_state.selected_model = list(ClaudeAPI.MODELS.keys())[0]
if 'theme' not in st.session_state:
    st.session_state.theme = "Light"
if 'system_prompt' not in st.session_state:
    st.session_state.system_prompt = "You are a helpful and accurate assistant."

# Sidebar
with st.sidebar:
    st.title("⚙️ Settings")

    # Theme
    theme = st.selectbox("🎨 Theme", ["Light", "Dark", "Auto"], key="theme_selector")

    # Aplicar tema imediatamente quando selecionado
    if theme != st.session_state.get('theme'):
        st.session_state.theme = theme

    # CSS para aplicar o tema
    if st.session_state.theme == "Dark":
        st.markdown("""
            <style>
                .stApp {
                    background-color: #1E1E1E;
                    color: #FFFFFF;
                }
                .stSidebar {
                    background-color: #2D2D2D;
                }
                .stChatMessage {
                    background-color: #2D2D2D;
                }
            </style>
        """, unsafe_allow_html=True)
    elif st.session_state.theme == "Light":
        st.markdown("""
            <style>
                .stApp {
                    background-color: #FFFFFF;
                    color: #000000;
                }
                .stSidebar {
                    background-color: #F0F2F6;
                }
            </style>
        """, unsafe_allow_html=True)

    # Model selection
    model = st.selectbox(
        "Model", 
        list(ClaudeAPI.MODELS.keys()), 
        format_func=lambda x: ClaudeAPI.MODELS[x],
        key='model_selector'
    )

    if model != st.session_state.selected_model:
        st.session_state.selected_model = model
        st.rerun()

    max_tokens_limit = ClaudeAPI.get_max_tokens(model)
    st.info(f"📊 Max tokens for this model: {max_tokens_limit:,}")

    # Parameters
    temp = st.slider("Temperature", 0.0, 1.0, 0.5, 0.1)
    max_t = st.slider(
        "Max Tokens", 
        100, 
        max_tokens_limit, 
        min(8000, max_tokens_limit),
        100
    )

    use_streaming = st.checkbox("🔄 Enable Streaming", value=True, 
                                help="See response in real time (recommended for long responses)")

    # System Prompt Customization
    with st.expander("📝 System Prompt"):
        st.session_state.system_prompt = st.text_area(
            "Define assistant behavior:",
            value=st.session_state.system_prompt,
            height=100
        )

    # Saved Conversations
    with st.expander("💾 Saved Conversations"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Save Current", use_container_width=True):
                save_conversation()

        saved_chats = list_saved_conversations()
        if saved_chats:
            selected_chat = st.selectbox("Load conversation:", saved_chats)
            with col2:
                if st.button("Load", use_container_width=True):
                    load_conversation(selected_chat)

    # Export Options
    with st.expander("📥 Export Conversation"):
        format_type = st.selectbox("Format:", ["Markdown", "JSON"])

        if st.button("Generate Export"):
            content = export_conversation(format_type)
            if content:
                file_ext = "md" if format_type == "Markdown" else "json"
                mime_type = "text/markdown" if format_type == "Markdown" else "application/json"

                st.download_button(
                    f"📥 Download {format_type}",
                    content,
                    f"chat_export.{file_ext}",
                    mime_type
                )

    # Statistics
    with st.expander("📊 Statistics"):
        if st.session_state.msgs:
            total_msgs = len(st.session_state.msgs)
            total_tokens = sum(estimate_tokens(m['content']) for m in st.session_state.msgs)

            col1, col2 = st.columns(2)
            col1.metric("Messages", total_msgs)
            col2.metric("Tokens", f"{total_tokens:,}")

            if total_msgs > 0:
                df = create_usage_dataframe(st.session_state.msgs)
                st.line_chart(df.set_index('Message')['Cumulative'])

    # Buttons
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ Clear", use_container_width=True): 
            st.session_state.msgs = []
            st.rerun()
    with col2:
        if st.button("📋 Copy All", use_container_width=True):
            if st.session_state.msgs:
                chat_text = "\n\n".join([
                    f"**{m['role'].title()}**: {m['content']}" 
                    for m in st.session_state.msgs
                ])
                st.text_area("Copy this text:", chat_text, height=200)
            else: 
                st.warning("No messages to copy")

    # Mermaid info
    st.divider()
    st.markdown("### 📊 Mermaid Support")
    st.info("This chat supports Mermaid diagram rendering! Ask Claude to create diagrams using ```mermaid``` syntax")

# Main chat interface
st.title("🤖 Claude Chat")

# Prompt Templates
col1, col2 = st.columns([4, 1])
with col2:
    template = st.selectbox("📝 Templates", [""] + list(ClaudeAPI.PROMPT_TEMPLATES.keys()))

template_prompt = ""
if template:
    template_prompt = ClaudeAPI.PROMPT_TEMPLATES[template]
    st.info(f"Template: {template_prompt}")

# Display chat history with metadata
for idx, m in enumerate(st.session_state.msgs): 
    with st.chat_message(m["role"]):
        display_message_with_metadata(m, idx)

# File uploader with extended support
files = st.file_uploader(
    "📎 Attach files", 
    accept_multiple_files=True, 
    type=['png','jpg','jpeg','txt','py','csv','md','json','cfg','php','sql','pdf','js','html','css','xml','yml','yaml','xlsx','docx','ipynb','zip']
)

# Chat input
if prompt := st.chat_input("Type your message..." if not template_prompt else template_prompt):
    if template_prompt and prompt == template_prompt:
        prompt = template_prompt

    st.session_state.msgs.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        history = [
            {"role": m["role"], "content": m["content"]} 
            for m in st.session_state.msgs[:-1]
        ]

        if use_streaming:
            message_placeholder = st.empty()
            full_response = ""

            for chunk in st.session_state.api.send_message_stream(
                prompt, model, temp, max_t, history, files, st.session_state.system_prompt
            ):
                full_response += chunk
                message_placeholder.markdown(full_response + "▼")

            message_placeholder.empty()
            render_message_with_mermaid(full_response)
            resp = full_response
        else:
            with st.spinner("Thinking..."):
                full_response = ""
                for chunk in st.session_state.api.send_message_stream(
                    prompt, model, temp, max_t, history, files, st.session_state.system_prompt
                ):
                    full_response += chunk
                resp = full_response

            render_message_with_mermaid(resp)

        st.session_state.msgs.append({"role": "assistant", "content": resp})