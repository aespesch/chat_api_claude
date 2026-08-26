0import os, streamlit as st, anthropic, base64, warnings, re, json, html, io, hashlib, logging
from pathlib import Path
from streamlit.components.v1 import html as st_html
from datetime import datetime, timedelta
import PyPDF2
import extra_streamlit_components as stx

warnings.filterwarnings('ignore')

# ============ LOGGING SETUP ============
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(funcName)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Silence noisy third-party loggers (httpx, httpcore, anthropic internals)
for _lib in ("httpx", "httpcore", "anthropic"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

st.set_page_config(page_title="Claude Chat", page_icon="🤖", layout="wide")

# ============ CONSTANTS ============

APP_VERSION = "1.4.0"
COOKIE_NAME = "claude_chat_auth"
COOKIE_EXPIRY_DAYS = 2  # 48 hours
DEFAULT_MODEL = "claude-haiku-4-5"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MERMAID_PATTERN = r'```mermaid\s*\n(.*?)```'       # for re.findall — extracts diagram content
MERMAID_SPLIT_PATTERN = r'```mermaid\s*\n.*?```'   # for re.split  — splits text around blocks

# Startup log — visible in Streamlit Cloud logs
logger.info(f"🚀 Loading Claude Chat v{APP_VERSION} | Default model: {DEFAULT_MODEL}")

# ============ INITIALIZE SESSION STATE EARLY ============
# CRITICAL: Initialize authenticated BEFORE check_password()
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

# ============ COOKIE-BASED PERSISTENT AUTHENTICATION (48h) ============

def get_cookie_manager():
    """Returns a singleton cookie manager instance."""
    return stx.CookieManager(key="cookie_manager_singleton")


def generate_auth_token(password: str) -> str:
    """
    Generates a deterministic auth token from the password + a secret salt.
    This token is stored in the cookie to validate future sessions.
    """
    salt = st.secrets.get("COOKIE_SECRET", "claude-chat-default-salt-change-me")
    raw = f"{password}:{salt}:claude-chat-persistent"
    return hashlib.sha256(raw.encode()).hexdigest()


def check_password():
    """
    Returns True if the user is authenticated.
    Authentication persists for 48h via a browser cookie.
    """
    # 1) Check in-memory session first (fastest path)
    #    IMPORTANT: return BEFORE creating CookieManager component.
    #    The CookieManager is a React component that triggers a Streamlit
    #    rerun ~1s after mounting, which kills any active streaming generator.
    if st.session_state.get("authenticated"):
        logger.info("✅ User already authenticated in session")
        return True

    # 2) Only create CookieManager when we actually need it (not yet authenticated)
    cookie_manager = get_cookie_manager()

    # 3) Check cookie for persisted session
    auth_cookie = cookie_manager.get(COOKIE_NAME)
    logger.info(f"Cookie retrieved: {auth_cookie is not None}")

    if auth_cookie is not None:
        try:
            # CookieManager may return a dict or a JSON string depending on version
            cookie_data = auth_cookie if isinstance(auth_cookie, dict) else json.loads(auth_cookie)
            stored_token = cookie_data.get("token", "")
            expiry_str = cookie_data.get("expiry", "")
            logger.debug(f"Cookie parsed successfully | Expiry: {expiry_str}")

            if expiry_str:
                expiry_dt = datetime.fromisoformat(expiry_str)
                if datetime.now() < expiry_dt:
                    # Validate the token against the current password
                    correct_password = st.secrets.get("PWD", "")
                    expected_token = generate_auth_token(correct_password)

                    if stored_token == expected_token:
                        st.session_state.authenticated = True
                        logger.info("✅ User authenticated via valid cookie")
                        return True
                else:
                    logger.debug("❌ Cookie expired")

            # Cookie expired or invalid — remove it
            logger.info("Removing invalid/expired cookie")
            cookie_manager.delete(COOKIE_NAME)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # Malformed cookie — remove it
            logger.warning(f"⚠️ Cookie parsing error: {e}")
            cookie_manager.delete(COOKIE_NAME)

    # 4) Not authenticated — show login form
    st.title("🔐 Authentication Required")
    password = st.text_input("Enter password:", type="password", key="password_input")

    if st.button("Login", type="primary"):
        try:
            correct_password = st.secrets.get("PWD", "")
            if password == correct_password and password != "":
                # Generate token and set cookie for 48h
                token = generate_auth_token(password)
                expiry = datetime.now() + timedelta(days=COOKIE_EXPIRY_DAYS)
                cookie_value = json.dumps({
                    "token": token,
                    "expiry": expiry.isoformat()
                })
                cookie_manager.set(
                    COOKIE_NAME,
                    cookie_value,
                    expires_at=expiry,
                    key="set_auth_cookie"
                )
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("⛔ Unauthorized access. Invalid password.")
        except Exception as e:
            st.error(f"⛔ Configuration error: {str(e)}")

    return False


# ✅ CHECK PASSWORD BEFORE ANY API INITIALIZATION
if not check_password():
    st.stop()

# ============ REST OF THE APPLICATION ============

class APIError(Exception):
    """Custom API error class"""
    pass

class ClaudeAPI:
    MODELS = {
        "claude-fable-5": "Claude Fable 5 (Most Capable)",
        "claude-opus-5": "Claude Opus 5 (Most Intelligent)",
        "claude-sonnet-5": "Claude Sonnet 5 (Best Speed/Intelligence)",
        "claude-haiku-4-5": "Claude Haiku 4.5 (Fastest)",
    }

    MODEL_MAX_TOKENS = {
        "claude-fable-5": 128000,
        "claude-opus-5": 128000,
        "claude-sonnet-5": 128000,
        "claude-haiku-4-5": 64000,
    }

    # `temperature` was removed from the anthropic SDK 1.x signatures (passing it
    # raises TypeError) and current reasoning models reject it server-side too.
    # Only the models below still honour it, via `extra_body`.
    MODELS_WITH_TEMPERATURE = {
        "claude-haiku-4-5",
    }

    # Models that accept the `effort` parameter (sent as output_config.effort),
    # mapped to the effort levels each one supports. Haiku 4.5 has no effort.
    MODEL_EFFORT_LEVELS = {
        "claude-fable-5": ["low", "medium", "high", "xhigh", "max"],
        "claude-opus-5": ["low", "medium", "high", "xhigh", "max"],
        "claude-sonnet-5": ["low", "medium", "high", "xhigh", "max"],
    }
    DEFAULT_EFFORT = "high"  # API default; good balance of quality vs. cost

    # Fable 5 / Opus 5 may decline a request (stop_reason "refusal"). With
    # server-side fallback enabled the API re-runs the same request on a
    # fallback model inside the same call, routed by refusal category.
    ENABLE_REFUSAL_FALLBACK = True
    REFUSAL_FALLBACK_MODELS = {"claude-fable-5", "claude-opus-5"}
    REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"

    PROMPT_TEMPLATES = {
        "Code Review": "Analyze this code and suggest improvements:",
        "Summary": "Create an executive summary of the following text:",
        "Translation": "Translate the following text to {language}:",
        "Debug": "Find and fix errors in this code:",
        "Explain": "Explain this concept in simple terms:",
        "Refactor": "Refactor this code for better performance and readability:",
        "Rewrite": ("Rewrite the following text applying all of these guidelines:\n"
    "1. Fix any Portuguese language errors (spelling, grammar, agreement, verb/noun governance).\n"
    "2. Make the text more concise by removing unnecessary words and sentences.\n"
    "3. Remove redundancies and repeated ideas.\n"
    "4. Improve reading fluidity and clarity.\n"
    "5. Fully preserve all wikimedia/wikitext formatting "
    "(templates, internal/external links, tables, categories, references, HTML tags, etc.).\n\n"
    "Return only the rewritten text, without additional explanations.\n\n"
    "Text:"
     ),
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
        logger.debug("Validating API key...")
        try:
            self.client.messages.create(
                model=DEFAULT_MODEL,
                max_tokens=1,
                messages=[{"role": "user", "content": "Hi"}]
            )
            logger.info("✅ API key validated successfully")
            return True
        except Exception as e:
            logger.error(f"❌ API key validation failed: {e}")
            return False

    def send_message_stream(self, msg, model, temp=0.7, max_t=2000, hist=None, files=None, system_prompt=None, effort=None):
        """Stream version that returns a generator"""
        logger.debug(f"send_message_stream() called | model={model}, files={len(files or [])}, temp={temp}, effort={effort}")

        if not self.client:
            logger.error("❌ Client not initialized")
            yield "❌ API key not configured"
            return

        content = [{"type": "text", "text": sanitize_input(msg)}]

        if files:
            logger.debug(f"Processing {len(files)} files...")
            for f in files:
                f.seek(0)
                try:
                    processed_content = process_file(f)
                    if processed_content:
                        content.append(processed_content)
                        logger.debug(f"✅ Processed file: {f.name}")
                except Exception as e:
                    logger.error(f"❌ Error processing {f.name}: {e}")
                    st.warning(f"Could not process file {f.name}: {e}")

        msgs = (hist or []) + [{"role": "user", "content": content}]
        logger.debug(f"Message history: {len(msgs)} messages total")

        kwargs = {
            "model": model,
            "max_tokens": max_t,
            "messages": msgs
        }

        # `temperature` is no longer a parameter of the SDK's messages methods,
        # so it can only be sent through extra_body, and only to models that
        # still accept it. Current reasoning models return 400 if it is present.
        if model in self.MODELS_WITH_TEMPERATURE:
            kwargs["extra_body"] = {"temperature": temp}
        else:
            logger.debug(f"Skipping temperature for {model} (not supported)")

        # Effort controls reasoning depth / token spend on newer models.
        # Sent inside output_config (GA — no beta header needed).
        if effort and model in self.MODEL_EFFORT_LEVELS:
            kwargs["output_config"] = {"effort": effort}
            logger.debug(f"Using effort='{effort}' for {model}")

        if system_prompt:
            kwargs["system"] = system_prompt

        # Opt into server-side refusal fallback on the models that support it.
        # Sent as header + raw body so it works regardless of SDK version.
        if self.ENABLE_REFUSAL_FALLBACK and model in self.REFUSAL_FALLBACK_MODELS:
            kwargs["extra_headers"] = {"anthropic-beta": self.REFUSAL_FALLBACK_BETA}
            kwargs.setdefault("extra_body", {})["fallbacks"] = "default"
            logger.debug(f"Refusal fallback enabled for {model}")

        try:
            logger.debug(f"Starting stream to {model}...")
            with self.client.messages.stream(**kwargs) as stream:
                chunk_count = 0
                for text in stream.text_stream:
                    chunk_count += 1
                    yield text
                final = stream.get_final_message()
                logger.debug(f"✅ Stream completed | {chunk_count} chunks | "
                             f"stop_reason={final.stop_reason}")
                if final.stop_reason == "refusal":
                    yield "\n\n⚠️ The model declined to answer this request."
        except anthropic.RateLimitError as e:
            logger.warning(f"⏱️ Rate limit: {e}")
            yield "⏱️ Rate limit reached. Please wait a few seconds..."
        except anthropic.AuthenticationError as e:
            logger.error(f"🔐 Auth error: {e}")
            yield "🔐 Authentication error. Please check your API key."
        except (anthropic.NotFoundError, anthropic.PermissionDeniedError) as e:
            logger.error(f"🔍 Model unavailable: {type(e).__name__}: {e}")
            yield (f"❌ Model '{model}' is not available to this API key "
                   f"(not found or no access).\n\nDetails: {str(e)}")
        except anthropic.BadRequestError as e:
            logger.error(f"❌ Bad request: {e}")
            yield f"❌ Invalid request: {str(e)}"
        except Exception as e:
            logger.error(f"❌ Unexpected error in stream: {type(e).__name__}: {e}")
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
    """Sanitize user input for API consumption.

    Note: html.escape() is NOT used here because the text is sent
    to Claude's API (JSON), not rendered as raw HTML in a browser.
    Streamlit handles its own output sanitization.
    """
    # Remove null bytes and other control characters that could cause issues
    text = text.replace('\x00', '')
    # Strip leading/trailing whitespace
    text = text.strip()
    return text

def validate_file(file):
    """Validate file before processing"""
    if file.size > MAX_FILE_SIZE:
        raise ValueError(f"File too large: {file.size/1024/1024:.1f}MB")
    return True

FILE_PROCESSORS = {
    '.pdf':  lambda f: {"type": "text", "text": f"\n📄 {f.name} (PDF):\n```\n{extract_text_from_pdf_cached(f.read())}\n```"},
    '.xlsx': lambda f: {"type": "text", "text": f"\n📄 {f.name}: Excel file processing not implemented\n"},
    '.docx': lambda f: {"type": "text", "text": f"\n📄 {f.name}: Word file processing not implemented\n"},
    '.ipynb':lambda f: {"type": "text", "text": f"\n📄 {f.name}: Jupyter notebook processing not implemented\n"},
    '.zip':  lambda f: {"type": "text", "text": f"\n📄 {f.name}: ZIP file processing not implemented\n"},
}

TEXT_EXTENSIONS = ['.txt','.py','.csv','.md','.json','.php','.cfg','.sql','.js','.html','.css','.xml','.yml','.yaml']

LANG_MAP = {
    '.php': 'php', '.sql': 'sql', '.py': 'python',
    '.json': 'json', '.js': 'javascript', '.html': 'html',
    '.css': 'css', '.xml': 'xml', '.yml': 'yaml', '.yaml': 'yaml'
}

def process_file(file):
    """Universal file processor"""
    validate_file(file)
    extension = Path(file.name).suffix.lower()

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

    if extension in TEXT_EXTENSIONS:
        file.seek(0)
        text_content = file.read().decode('utf-8', errors='ignore')
        lang = LANG_MAP.get(extension, '')
        return {"type": "text", "text": f"\n📄 {file.name}:\n```{lang}\n{text_content}\n```"}

    return None

def estimate_tokens(text):
    """Estimate token count"""
    return len(text) // 4

def extract_mermaid_diagrams(text):
    """Extract all Mermaid diagrams from text"""
    return re.findall(MERMAID_PATTERN, text, re.DOTALL)

def render_mermaid(mermaid_code, key=None):
    """Render Mermaid diagram using HTML and JavaScript"""
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

def render_message_with_mermaid(content, render_diagrams=True):
    """Render message, processing Mermaid diagrams based on toggle setting"""
    mermaid_diagrams = extract_mermaid_diagrams(content)

    if not mermaid_diagrams or not render_diagrams:
        st.markdown(content)
        return

    parts = re.split(MERMAID_SPLIT_PATTERN, content, flags=re.DOTALL)

    for i, part in enumerate(parts):
        if part.strip():
            st.markdown(part)

        if i < len(mermaid_diagrams):
            st.markdown("**📊 Diagram:**")
            render_mermaid(mermaid_diagrams[i], key=f"mermaid_{i}_{hash(content)}")

def display_message_with_metadata(message, idx, render_mermaid_diagrams=True):
    """Display message with useful metadata"""
    col1, col2, col3 = st.columns([8, 1, 1])

    with col1:
        render_message_with_mermaid(message['content'], render_mermaid_diagrams)

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

    st.session_state.saved_conversations[filename] = {
        "timestamp": timestamp,
        "messages": st.session_state.msgs,
        "model": st.session_state.selected_model
    }
    st.success(f"Conversation saved as {filename}")

def load_conversation(filename):
    """Load saved conversation"""
    if filename in st.session_state.saved_conversations:
        data = st.session_state.saved_conversations[filename]
        st.session_state.msgs = data["messages"]
        st.session_state.selected_model = data.get("model", DEFAULT_MODEL)
        st.success("Conversation loaded")
        st.rerun()

def list_saved_conversations():
    """List all saved conversations"""
    return list(st.session_state.saved_conversations.keys())

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

# ============ INITIALIZE SESSION STATE ============
if 'msgs' not in st.session_state:
    st.session_state.msgs = []
if 'api' not in st.session_state:
    st.session_state.api = ClaudeAPI()
if 'selected_model' not in st.session_state:
    st.session_state.selected_model = DEFAULT_MODEL
if 'model_selector' not in st.session_state:
    st.session_state.model_selector = DEFAULT_MODEL
if 'theme' not in st.session_state:
    st.session_state.theme = "Light"
if 'system_prompt' not in st.session_state:
    st.session_state.system_prompt = "You are a helpful and accurate assistant."
if 'enable_mermaid' not in st.session_state:
    st.session_state.enable_mermaid = True
if 'saved_conversations' not in st.session_state:
    st.session_state.saved_conversations = {}

# ============ SIDEBAR ============
with st.sidebar:
    st.title("⚙️ Settings")

    # Theme
    theme = st.selectbox("🎨 Theme", ["Light", "Dark", "Auto"], key="theme_selector")

    if theme != st.session_state.get('theme'):
        st.session_state.theme = theme

    if st.session_state.theme == "Dark":
        st.markdown("""
            <style>
                :root { color-scheme: dark; }
                .stApp, .main, [data-testid="stAppViewContainer"] {
                    background-color: #1E1E1E !important; color: #FFFFFF !important;
                }
                header, [data-testid="stHeader"], .stAppHeader {
                    background-color: #1E1E1E !important; color: #FFFFFF !important;
                }
                header[data-testid="stHeader"] { background-color: #1E1E1E !important; }
                [data-testid="stSidebar"] { background-color: #252526 !important; color: #FFFFFF !important; }
                [data-testid="stSidebar"] * { color: #FFFFFF !important; }
                p, span, div, label, h1, h2, h3, h4, h5, h6 { color: #FFFFFF !important; }
                .stTextInput > div > div > input,
                .stTextArea > div > div > textarea,
                .stNumberInput > div > div > input {
                    background-color: #3C3C3C !important; color: #FFFFFF !important; border-color: #555555 !important;
                }
                .stSelectbox > div > div, [data-testid="stSelectbox"] > div > div {
                    background-color: #3C3C3C !important; color: #FFFFFF !important;
                }
                .stMultiSelect > div > div { background-color: #3C3C3C !important; color: #FFFFFF !important; }
                .stButton > button { background-color: #0E639C !important; color: #FFFFFF !important; border: none !important; }
                .stButton > button:hover { background-color: #1177BB !important; }
                .stDownloadButton > button { background-color: #0E639C !important; color: #FFFFFF !important; }
                [data-testid="stChatMessage"] { background-color: #2D2D2D !important; }
                [data-testid="stChatMessageContent"] { color: #FFFFFF !important; }
                [data-testid="stChatInput"] { background-color: #3C3C3C !important; }
                [data-testid="stChatInput"] textarea { background-color: #3C3C3C !important; color: #FFFFFF !important; }
                [data-testid="stFileUploader"] { background-color: #2D2D2D !important; }
                [data-testid="stFileUploader"] * { color: #FFFFFF !important; }
                .streamlit-expanderHeader { background-color: #2D2D2D !important; color: #FFFFFF !important; }
                .streamlit-expanderContent { background-color: #252526 !important; }
                [data-testid="stMetric"] { background-color: #2D2D2D !important; }
                [data-testid="stMetricValue"] { color: #FFFFFF !important; }
                [data-testid="stMetricLabel"] { color: #CCCCCC !important; }
                .stAlert { background-color: #2D2D2D !important; color: #FFFFFF !important; }
                .stCodeBlock { background-color: #1E1E1E !important; }
                code { background-color: #2D2D2D !important; color: #CE9178 !important; }
                pre { background-color: #1E1E1E !important; }
                .stDataFrame { background-color: #2D2D2D !important; }
                .stSlider > div > div > div { background-color: #0E639C !important; }
                .stProgress > div > div { background-color: #0E639C !important; }
                .stTabs [data-baseweb="tab-list"] { background-color: #252526 !important; }
                .stTabs [data-baseweb="tab"] { color: #FFFFFF !important; }
                hr, [data-testid="stHorizontalBlock"] { border-color: #555555 !important; }
                .stCaption, small, figcaption { color: #AAAAAA !important; }
                .stCheckbox label span { color: #FFFFFF !important; }
                a { color: #6CB4EE !important; }
                [data-testid="stTooltipIcon"] { color: #AAAAAA !important; }
                [data-testid="stVegaLiteChart"] { background-color: #2D2D2D !important; }
                [data-testid="stEmpty"] { background-color: #1E1E1E !important; }
                .stSpinner > div { border-color: #FFFFFF transparent transparent transparent !important; }
            </style>
        """, unsafe_allow_html=True)
    elif st.session_state.theme == "Light":
        st.markdown("""
            <style>
                .stApp { background-color: #FFFFFF; color: #000000; }
                [data-testid="stSidebar"] { background-color: #F0F2F6; }
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
    if model in ClaudeAPI.MODELS_WITH_TEMPERATURE:
        temp = st.slider("Temperature", 0.0, 1.0, 0.5, 0.1)
    else:
        temp = 0.5  # placeholder; not sent for models that dropped temperature
        st.caption("🌡️ Temperature is not configurable for this model (uses adaptive reasoning).")

    # Effort: controls reasoning depth and token spend on newer models.
    effort_levels = ClaudeAPI.MODEL_EFFORT_LEVELS.get(model)
    if effort_levels:
        effort = st.selectbox(
            "🧠 Effort",
            effort_levels,
            index=effort_levels.index(ClaudeAPI.DEFAULT_EFFORT),
            help="Higher effort = more thorough reasoning, but slower and more tokens. "
                 "Default: high; 'xhigh' suits coding/agentic work; 'max' for hard problems.",
        )
    else:
        effort = None

    max_t = st.slider(
        "Max Tokens",
        100,
        max_tokens_limit,
        max_tokens_limit,
        100
    )

    use_streaming = st.checkbox("🔄 Enable Streaming", value=True,
                                help="See response in real time (recommended for long responses)")

    enable_mermaid = st.checkbox("📊 Enable Mermaid Diagrams", value=st.session_state.enable_mermaid,
                                 help="When enabled, renders Mermaid diagrams visually. When disabled, shows the source code.")
    st.session_state.enable_mermaid = enable_mermaid

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

    # Logout and About buttons
    st.divider()
    if st.button("🚪 Logout", use_container_width=True):
        cookie_manager = get_cookie_manager()
        cookie_manager.delete(COOKIE_NAME, key="delete_auth_cookie_logout")
        st.session_state.authenticated = False
        st.session_state.msgs = []
        st.rerun()

    if st.button("ℹ️ About", use_container_width=True):
        st.info(
            f"**Claude Chat** v{APP_VERSION}\n\n"
            f"Default model: `{DEFAULT_MODEL}`\n\n"
            f"Active model: `{st.session_state.selected_model}`"
        )

# ============ MAIN CHAT INTERFACE ============
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
        display_message_with_metadata(m, idx, st.session_state.enable_mermaid)

# File uploader with extended support
files = st.file_uploader(
    "📎 Attach files",
    accept_multiple_files=True,
    type=['png','jpg','jpeg','txt','py','csv','md','json','cfg','php','sql','pdf','js','html','css','xml','yml','yaml','xlsx','docx','ipynb','zip']
)

# Chat input
if prompt := st.chat_input("Type your message..." if not template_prompt else f"[{template}] Type your text here..."):
    logger.info(f"📝 User input received | Length: {len(prompt)}")

    # ✅ CONCATENATE template + user text
    if template_prompt:
        full_prompt = f"{template_prompt}\n\n{prompt}"
        # Show to user what they typed (without template, to avoid clutter)
        display_prompt = f"**[{template}]**\n\n{prompt}"
    else:
        full_prompt = prompt
        display_prompt = prompt

    st.session_state.msgs.append({"role": "user", "content": display_prompt})
    with st.chat_message("user"):
        st.markdown(display_prompt)

    # Handle /model command
    if prompt.strip().lower() == "/model":
        logger.debug("Executing /model command")
        with st.chat_message("assistant"):
            try:
                test_resp = st.session_state.api.client.messages.create(
                    model=model,
                    max_tokens=16,  # 1 can be rejected by adaptive-thinking models
                    messages=[{"role": "user", "content": "Hi"}]
                )
                actual_model = test_resp.model
                expected_label = ClaudeAPI.MODELS.get(model, model)
                match = "✅ Models match!" if model in actual_model else "⚠️ Models DIFFER!"
                resp = (
                    f"🤖 **Selected in UI:** {expected_label} (`{model}`)\n\n"
                    f"🔍 **Returned by API:** `{actual_model}`\n\n"
                    f"{match}"
                )
                logger.info(f"✅ /model command executed | UI: {model} | API: {actual_model}")
            except Exception as e:
                logger.error(f"❌ /model command error: {e}")
                resp = f"❌ Error checking model: {e}"
            st.markdown(resp)
        st.session_state.msgs.append({"role": "assistant", "content": resp})
        st.stop()

    with st.chat_message("assistant"):
        logger.info(f"💬 Processing message | Model: {model} | Streaming: {use_streaming} | Template: {template or 'None'}")
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.msgs[:-1]
        ]
        # ✅ Send full_prompt (template + text) instead of just prompt
        stream_args = (full_prompt, model, temp, max_t, history, files, st.session_state.system_prompt, effort)

        if use_streaming:
            logger.debug("Using streaming mode")
            message_placeholder = st.empty()
            full_response = ""

            for chunk in st.session_state.api.send_message_stream(*stream_args):
                full_response += chunk
                message_placeholder.markdown(full_response + "▼")

            message_placeholder.empty()
            render_message_with_mermaid(full_response, st.session_state.enable_mermaid)
            resp = full_response
            logger.info(f"✅ Streaming response completed | Length: {len(resp)}")
        else:
            logger.debug("Using non-streaming mode")
            with st.spinner("Thinking..."):
                resp = "".join(st.session_state.api.send_message_stream(*stream_args))

            render_message_with_mermaid(resp, st.session_state.enable_mermaid)
            logger.info(f"✅ Non-streaming response completed | Length: {len(resp)}")

        st.session_state.msgs.append({"role": "assistant", "content": resp})