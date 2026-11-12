import os, streamlit as st, anthropic, base64, warnings, re, json, html, io, hashlib, logging, time, threading, uuid, tempfile
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

APP_VERSION = "1.7.0"
COOKIE_NAME = "claude_chat_auth"
COOKIE_EXPIRY_DAYS = 2  # 48 hours
DEFAULT_MODEL = "claude-haiku-5-5"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MERMAID_PATTERN = r'```mermaid\s*\n(.*?)```'       # for re.findall — extracts diagram content
MERMAID_SPLIT_PATTERN = r'```mermaid\s*\n.*?```'   # for re.split  — splits text around blocks

# Persistence
CHAT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PARTIAL_FLUSH_SECONDS = 1.0     # how often the background thread saves partial text
IMAGE_TOKEN_ESTIMATE = 1600     # rough token estimate per image (fallback cost only)

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
        "claude-fable-5-2": "Claude Fable 5.2 (Most Capable)",
        "claude-opus-5-5": "Claude Opus 5.5 (Most Intelligent)",
        "claude-sonnet-5-5": "Claude Sonnet 5.5 (Best Speed/Intelligence)",
        "claude-haiku-5-5": "Claude Haiku 5.5 (Fastest)",
    }

    # Price in USD per million tokens (MTok).
    # Single value per model: applied to both input and output tokens.
    MODEL_PRICES = {
        "claude-fable-5-2": 40.0,
        "claude-opus-5-5": 20.0,
        "claude-sonnet-5-5": 10.0,
        "claude-haiku-5-5": 0.5,
    }

    MODEL_MAX_TOKENS = {
        "claude-fable-5-2": 128000,
        "claude-opus-5-5": 128000,
        "claude-sonnet-5-5": 128000,
        "claude-haiku-5-5": 64000,
    }

    # ------------------------------------------------------------------
    # TEMPERATURE SUPPORT
    # ------------------------------------------------------------------
    # `temperature` was removed from the anthropic SDK 1.x method signatures
    # (passing it directly raises TypeError) AND the current model generation
    # rejects it server-side with:
    #     400 invalid_request_error:
    #     "temperature: Extra inputs are not permitted"
    # ...even when smuggled through `extra_body`.
    #
    # => The allowlist is intentionally EMPTY: temperature is never sent.
    #    If/when a future model re-enables it, just add its id here and the
    #    sidebar slider + request payload wiring come back automatically.
    MODELS_WITH_TEMPERATURE: set = set()

    # Models that accept the `effort` parameter (sent as output_config.effort),
    # mapped to the effort levels each one supports. Haiku has no effort.
    MODEL_EFFORT_LEVELS = {
        "claude-fable-5-2": ["low", "medium", "high", "xhigh", "max"],
        "claude-opus-5-5": ["low", "medium", "high", "xhigh", "max"],
        "claude-sonnet-5-5": ["low", "medium", "high", "xhigh", "max"],
    }
    DEFAULT_EFFORT = "high"  # API default; good balance of quality vs. cost

    # Fable / Opus may decline a request (stop_reason "refusal"). With
    # server-side fallback enabled the API re-runs the same request on a
    # fallback model inside the same call, routed by refusal category.
    ENABLE_REFUSAL_FALLBACK = True
    REFUSAL_FALLBACK_MODELS = {"claude-fable-5-2", "claude-opus-5-5"}
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

    @classmethod
    def get_price(cls, model):
        """Returns price in USD per million tokens (MTok) for a model"""
        return cls.MODEL_PRICES.get(model, 0.0)

    @classmethod
    def estimate_cost(cls, model, input_tokens, output_tokens):
        """Estimates cost in USD given token counts"""
        price = cls.get_price(model)
        return (input_tokens + output_tokens) / 1_000_000 * price

    @classmethod
    def supports_temperature(cls, model: str) -> bool:
        """True only for models that still accept the `temperature` parameter."""
        return model in cls.MODELS_WITH_TEMPERATURE

    @staticmethod
    def _strip_unsupported_params(kwargs: dict, model: str) -> dict:
        """
        Safety net executed right before every API call.

        Guarantees that `temperature` (and `top_p`/`top_k`, which share the same
        restriction on reasoning models) never reaches the API for a model that
        does not support it — no matter where in the code it was injected.
        Also drops `extra_body` entirely if it ends up empty, so we don't send
        a stray `{}` payload.
        """
        banned = ("temperature", "top_p", "top_k")

        # Top-level (shouldn't happen with SDK 1.x, but be defensive)
        for key in banned:
            if key in kwargs and not ClaudeAPI.supports_temperature(model):
                kwargs.pop(key, None)
                logger.warning(f"🧹 Stripped top-level '{key}' for {model}")

        extra_body = kwargs.get("extra_body")
        if isinstance(extra_body, dict):
            if not ClaudeAPI.supports_temperature(model):
                for key in banned:
                    if key in extra_body:
                        extra_body.pop(key, None)
                        logger.warning(f"🧹 Stripped extra_body['{key}'] for {model}")
            if not extra_body:
                kwargs.pop("extra_body", None)

        return kwargs

    def __init__(self):
        self.last_usage = None  # real token usage from the latest API call
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
        """Validate API key with minimal call (uses the cheapest model)"""
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

    def build_user_content(self, msg, files=None):
        """Builds the user content blocks. Runs in the MAIN script thread
        (reads UploadedFile objects).

        Returns (content, attached_names, errors):
          - content: list of API content blocks (text + images + file texts)
          - attached_names: names of the files successfully added to `content`
          - errors: human-readable error strings for files that failed
        """
        content, attached, errors = [], [], []

        text = sanitize_input(msg)
        if text:  # the API rejects empty text blocks
            content.append({"type": "text", "text": text})

        for f in (files or []):
            try:
                f.seek(0)
                processed = process_file(f)
                if processed:
                    content.append(processed)
                    attached.append(f.name)
                    logger.debug(f"✅ Processed file: {f.name}")
                else:
                    errors.append(f"{f.name}: unsupported file type")
            except Exception as e:
                logger.error(f"❌ Error processing {f.name}: {e}")
                errors.append(f"{f.name}: {e}")

        if not content:
            content.append({"type": "text", "text": "(empty message)"})
        return content, attached, errors

    def send_message_stream(self, content, model, temp=None, max_t=2000, hist=None,
                            system_prompt=None, effort=None, on_usage=None):
        """
        Stream generator. Receives the already-built `content` blocks.
        IMPORTANT: runs inside a background thread -> must NOT call st.* here.

        `temp` is accepted for signature compatibility but is only forwarded to
        models listed in MODELS_WITH_TEMPERATURE (currently none).

        `on_usage(dict)` is called with the real token usage when the stream
        completes (per-job callback, so concurrent jobs don't clobber each other).
        """
        logger.debug(f"send_message_stream() called | model={model}, effort={effort}")
        self.last_usage = None

        if not self.client:
            logger.error("❌ Client not initialized")
            yield "❌ API key not configured"
            return

        msgs = (hist or []) + [{"role": "user", "content": content}]
        logger.debug(f"Message history: {len(msgs)} messages total")

        kwargs = {"model": model, "max_tokens": max_t, "messages": msgs}

        # Temperature: only for models that still accept it (allowlist is empty).
        if temp is not None and self.supports_temperature(model):
            kwargs["extra_body"] = {"temperature": temp}

        # Effort controls reasoning depth / token spend on newer models.
        # Sent inside output_config (GA — no beta header needed).
        if effort and model in self.MODEL_EFFORT_LEVELS:
            kwargs["output_config"] = {"effort": effort}

        if system_prompt:
            kwargs["system"] = system_prompt

        # Opt into server-side refusal fallback on the models that support it.
        # Sent as header + raw body so it works regardless of SDK version.
        if self.ENABLE_REFUSAL_FALLBACK and model in self.REFUSAL_FALLBACK_MODELS:
            kwargs["extra_headers"] = {"anthropic-beta": self.REFUSAL_FALLBACK_BETA}
            kwargs.setdefault("extra_body", {})["fallbacks"] = "default"

        # 🔒 Final guard: never let temperature/top_p/top_k slip through.
        kwargs = self._strip_unsupported_params(kwargs, model)

        try:
            with self.client.messages.stream(**kwargs) as stream:
                chunk_count = 0
                for text in stream.text_stream:
                    chunk_count += 1
                    yield text
                final = stream.get_final_message()
                try:
                    usage = {
                        "input_tokens": final.usage.input_tokens,
                        "output_tokens": final.usage.output_tokens,
                    }
                except Exception:
                    usage = None
                self.last_usage = usage
                if on_usage is not None:
                    try:
                        on_usage(usage)
                    except Exception as cb_err:
                        logger.warning(f"⚠️ on_usage callback failed: {cb_err}")
                logger.info(f"✅ Stream completed | {chunk_count} chunks | "
                            f"stop_reason={final.stop_reason} | usage={usage}")
                if final.stop_reason == "refusal":
                    yield "\n\n⚠️ The model declined to answer this request."
                elif final.stop_reason == "max_tokens":
                    yield "\n\n⚠️ Response truncated: max tokens limit reached."
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

def estimate_content_tokens(content):
    """Estimate tokens for either a plain string or a list of API content blocks."""
    if isinstance(content, str):
        return estimate_tokens(content)
    total = 0
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            total += estimate_tokens(block.get("text", ""))
        elif block.get("type") == "image":
            total += IMAGE_TOKEN_ESTIMATE
    return total

def message_context_tokens(message):
    """Estimated tokens this message contributes to the context (incl. attachments)."""
    return estimate_content_tokens(message.get("api_content") or message.get("content", ""))

def build_api_history(messages, keep_attachments=True):
    """
    Builds the history sent to the API from stored messages.

    User messages carry:
      - `api_content`: the full content blocks (text + images + file contents)
      - `prompt_text`: the real prompt (template text included)
    so follow-up questions still "see" previously attached files.
    `content` is only the display text and is used as a fallback for legacy messages.
    """
    hist = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue

        if role == "user":
            if keep_attachments and m.get("api_content"):
                content = m["api_content"]
            else:
                content = m.get("prompt_text") or m.get("content", "")
                if m.get("attachments"):
                    content += ("\n\n[Attachments omitted from context: "
                                + ", ".join(m["attachments"]) + "]")
        else:
            content = m.get("content", "")

        if not content:  # the API rejects empty messages
            continue
        hist.append({"role": role, "content": content})
    return hist

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
        if message.get("attachments"):
            st.caption("📎 In context: " + ", ".join(message["attachments"]))
        if message.get("meta"):
            st.caption(message["meta"])

    with col2:
        token_count = message_context_tokens(message)
        st.caption(f"🔤 {token_count:,}")

    with col3:
        if st.button("📋", key=f"copy_{idx}", help="Copy"):
            st.code(message['content'])

def export_conversation(format_type="Markdown"):
    """Export conversation in different formats"""
    if not st.session_state.msgs:
        return None

    if format_type == "Markdown":
        content = "# Chat Export\n\n"
        for msg in st.session_state.msgs:
            role = msg['role'].capitalize()
            content += f"## {role}\n\n{msg['content']}\n\n"
            if msg.get("attachments"):
                content += f"_Attachments: {', '.join(msg['attachments'])}_\n\n"
            content += "---\n\n"
        return content
    elif format_type == "JSON":
        # api_content is omitted: it may contain large base64 images
        light = [{k: v for k, v in m.items() if k != "api_content"}
                 for m in st.session_state.msgs]
        return json.dumps(light, indent=2, ensure_ascii=False)

    return None

def create_usage_dataframe(messages):
    """Create usage statistics dataframe"""
    import pandas as pd

    data = []
    total_tokens = 0
    for i, msg in enumerate(messages):
        tokens = message_context_tokens(msg)
        total_tokens += tokens
        data.append({
            'Message': i + 1,
            'Role': msg['role'],
            'Tokens': tokens,
            'Cumulative': total_tokens
        })

    return pd.DataFrame(data)

# ============ DISK PERSISTENCE ============

def _now_iso():
    return datetime.now().isoformat(timespec="seconds")

def is_valid_chat_id(chat_id) -> bool:
    """Only [A-Za-z0-9_-]: prevents path traversal through the ?chat= URL param."""
    return isinstance(chat_id, str) and bool(CHAT_ID_PATTERN.match(chat_id))

def new_chat_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]

def _resolve_data_dir() -> Path:
    """Storage directory: env CHAT_DATA_DIR > secrets CHAT_DATA_DIR > ./chat_data > tmp."""
    configured = os.getenv("CHAT_DATA_DIR")
    if not configured:
        try:
            configured = st.secrets.get("CHAT_DATA_DIR")
        except Exception:
            configured = None

    candidates = [Path(configured).expanduser()] if configured else []
    candidates += [
        Path(__file__).resolve().parent / "chat_data",
        Path(tempfile.gettempdir()) / "claude_chat_data",
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("ok")
            probe.unlink()
            return candidate
        except OSError as e:
            logger.warning(f"⚠️ Storage dir not writable: {candidate} ({e})")
    raise RuntimeError("No writable directory available for chat storage")


class ChatStore:
    """
    JSON-file storage for conversations.

      <root>/chats/<chat_id>.json     full conversation (messages, cost, pending job)
      <root>/partials/<job_id>.json   partial text of an in-progress answer
      <root>/index.json               lightweight list for the sidebar

    Thread-safe (per-chat RLocks) and crash-safe (atomic write + os.replace).
    Lock order used across the app: job commit lock -> chat lock -> index lock
    (the job registry lock is always taken last and never held while taking others).
    """

    SCHEMA_VERSION = 1

    def __init__(self, root: Path):
        self.root = Path(root)
        self.chats_dir = self.root / "chats"
        self.partials_dir = self.root / "partials"
        self.index_path = self.root / "index.json"
        self.chats_dir.mkdir(parents=True, exist_ok=True)
        self.partials_dir.mkdir(parents=True, exist_ok=True)
        self._locks = {}
        self._locks_guard = threading.Lock()
        self._index_lock = threading.RLock()
        logger.info(f"💾 Chat storage at: {self.root}")

    # ---------- low level ----------
    @staticmethod
    def _write_json_atomic(path: Path, obj):
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(5):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:  # Windows: target briefly opened by a reader
                    if attempt == 4:
                        raise
                    time.sleep(0.05)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    @staticmethod
    def _read_json(path: Path):
        """Parsed JSON, or None if missing. Corrupt files are quarantined, not overwritten."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            bad = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
            logger.error(f"❌ Corrupt JSON {path.name} ({e}) — moved to {bad.name}")
            try:
                path.rename(bad)
            except OSError:
                pass
            return None

    def lock(self, chat_id):
        with self._locks_guard:
            lk = self._locks.get(chat_id)
            if lk is None:
                lk = self._locks[chat_id] = threading.RLock()
            return lk

    def _chat_path(self, chat_id) -> Path:
        if not is_valid_chat_id(chat_id):
            raise ValueError(f"Invalid chat id: {chat_id!r}")
        return self.chats_dir / f"{chat_id}.json"

    def _partial_path(self, job_id) -> Path:
        if not is_valid_chat_id(job_id):
            raise ValueError(f"Invalid job id: {job_id!r}")
        return self.partials_dir / f"{job_id}.json"

    # ---------- conversations ----------
    @classmethod
    def new_chat_data(cls, chat_id, model=DEFAULT_MODEL):
        now = _now_iso()
        return {
            "version": cls.SCHEMA_VERSION,
            "id": chat_id,
            "created": now,
            "updated": now,
            "model": model,
            "cost": 0.0,
            "messages": [],
            "pending": None,   # {"job_id", "model", "started_at"} while generating
        }

    def exists(self, chat_id) -> bool:
        return is_valid_chat_id(chat_id) and self._chat_path(chat_id).exists()

    def load(self, chat_id) -> dict:
        """Loads a chat; returns fresh (unsaved) data if it doesn't exist yet."""
        data = self._read_json(self._chat_path(chat_id))
        if not isinstance(data, dict):
            data = self.new_chat_data(chat_id)
        defaults = self.new_chat_data(chat_id)
        for key, value in defaults.items():
            data.setdefault(key, value)
        if not isinstance(data.get("messages"), list):
            data["messages"] = []
        return data

    def save(self, chat_id, data):
        with self.lock(chat_id):
            data["id"] = chat_id
            data["updated"] = _now_iso()
            self._write_json_atomic(self._chat_path(chat_id), data)
            self._index_set(chat_id, self._index_entry(data))

    def update(self, chat_id, mutator) -> dict:
        """Atomic read-modify-write: load -> mutator(data) -> save."""
        with self.lock(chat_id):
            data = self.load(chat_id)
            mutator(data)
            self.save(chat_id, data)
            return data

    def delete(self, chat_id):
        with self.lock(chat_id):
            path = self._chat_path(chat_id)
            data = self._read_json(path)
            if isinstance(data, dict) and isinstance(data.get("pending"), dict):
                self.delete_partial(data["pending"].get("job_id"))
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            self._index_set(chat_id, None)
        logger.info(f"🗑️ Chat deleted: {chat_id}")

    # ---------- partial answers ----------
    def write_partial(self, job_id, payload: dict):
        self._write_json_atomic(self._partial_path(job_id), payload)

    def read_partial(self, job_id):
        if not is_valid_chat_id(job_id):
            return None
        data = self._read_json(self._partial_path(job_id))
        return data if isinstance(data, dict) else None

    def delete_partial(self, job_id):
        if not is_valid_chat_id(job_id):
            return
        try:
            self._partial_path(job_id).unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"⚠️ Could not delete partial {job_id}: {e}")

    # ---------- index ----------
    @staticmethod
    def _index_entry(data):
        title = "(empty)"
        for m in data.get("messages", []):
            if m.get("role") == "user":
                t = re.sub(r"\s+", " ", str(m.get("content", ""))).strip()
                if t:
                    title = (t[:60] + "…") if len(t) > 60 else t
                break
        return {
            "title": title,
            "created": data.get("created", ""),
            "updated": data.get("updated", ""),
            "messages": len(data.get("messages", [])),
            "pending": bool(data.get("pending")),
        }

    def _rebuild_index(self):
        idx = {}
        for p in self.chats_dir.glob("*.json"):
            if not is_valid_chat_id(p.stem):
                continue
            data = self._read_json(p)
            if isinstance(data, dict):
                idx[p.stem] = self._index_entry(data)
        self._write_json_atomic(self.index_path, idx)
        logger.info(f"🔁 Chat index rebuilt ({len(idx)} chats)")
        return idx

    def _load_index(self):
        idx = self._read_json(self.index_path)
        if not isinstance(idx, dict):
            idx = self._rebuild_index()
        return idx

    def _index_set(self, chat_id, entry):
        with self._index_lock:
            idx = self._load_index()
            if entry is None:
                idx.pop(chat_id, None)
            else:
                idx[chat_id] = entry
            self._write_json_atomic(self.index_path, idx)

    def list_chats(self):
        with self._index_lock:
            idx = self._load_index()
        items = [{"id": k, **v} for k, v in idx.items()
                 if is_valid_chat_id(k) and isinstance(v, dict)]
        items.sort(key=lambda c: c.get("updated", ""), reverse=True)
        return items

    def most_recent(self):
        for c in self.list_chats():
            if self.exists(c["id"]):
                return c["id"]
        return None


class JobRegistry:
    """Process-wide registry of running jobs, so a NEW session (tab reopened,
    session expired) can re-attach to a generation that is still running."""

    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

    def add(self, job):
        with self._lock:
            self._jobs[job.job_id] = job

    def remove(self, job_id):
        with self._lock:
            self._jobs.pop(job_id, None)

    def get(self, job_id):
        if not job_id:
            return None
        with self._lock:
            return self._jobs.get(job_id)

    def for_chat(self, chat_id):
        with self._lock:
            return [j for j in self._jobs.values() if j.chat_id == chat_id]


@st.cache_resource(show_spinner=False)
def get_chat_store():
    return ChatStore(_resolve_data_dir())

@st.cache_resource(show_spinner=False)
def get_job_registry():
    return JobRegistry()

STORE = get_chat_store()
JOBS = get_job_registry()

# ============ BACKGROUND GENERATION (survives reruns, sessions and tab closes) ============

class StreamJob:
    """
    Runs the API stream in a background thread and accumulates the text.

    The job does NOT depend on st.session_state:
      - partial text is flushed to disk every PARTIAL_FLUSH_SECONDS;
      - when finished (or stopped), the thread itself appends the answer to the
        conversation file on disk.
    So even if the browser session is destroyed, the answer is not lost; and if
    the server restarts mid-generation, the partial text is recovered on reopen.
    """

    def __init__(self, store, registry, chat_id, api, content, model, temp, max_t,
                 history, system_prompt, effort, input_tokens_est):
        self.job_id = uuid.uuid4().hex
        self.chat_id = chat_id
        self.store = store
        self.registry = registry
        self.model = model
        self.history = history
        self.input_tokens_est = input_tokens_est
        self.started_at = time.time()
        self.finished_at = None
        self.usage = None
        self.cost = 0.0
        self.committed = False
        self.commit_error = None
        self._discard = False
        self._parts = []
        self._lock = threading.Lock()
        self._commit_lock = threading.RLock()
        self._done = threading.Event()
        self._cancel = threading.Event()
        self._args = (api, content, temp, max_t, system_prompt, effort)

    def start(self):
        threading.Thread(
            target=self._run,
            args=self._args,
            daemon=True,
            name=f"stream-{self.job_id[:8]}",
        ).start()

    # ---------- background thread ----------
    def _set_usage(self, usage):
        self.usage = usage

    def _run(self, api, content, temp, max_t, system_prompt, effort):
        gen = api.send_message_stream(content, self.model, temp, max_t,
                                      self.history, system_prompt, effort,
                                      on_usage=self._set_usage)
        last_flush = 0.0
        try:
            for chunk in gen:
                if self._cancel.is_set():
                    break
                with self._lock:
                    self._parts.append(chunk)
                now = time.time()
                if now - last_flush >= PARTIAL_FLUSH_SECONDS:
                    self._flush_partial()
                    last_flush = now
        except Exception as e:
            logger.error(f"❌ StreamJob error: {type(e).__name__}: {e}")
            with self._lock:
                self._parts.append(f"\n\n❌ Unexpected error: {e}")
        finally:
            try:
                gen.close()  # closes the HTTP stream if we stopped early
            except Exception:
                pass
            if self.finished_at is None:
                self.finished_at = time.time()
            self._commit()   # no-op if already committed (Stop / discard)
            self._done.set()

    def _flush_partial(self):
        with self._commit_lock:
            if self.committed:
                return
            try:
                self.store.write_partial(self.job_id, {
                    "job_id": self.job_id,
                    "chat_id": self.chat_id,
                    "model": self.model,
                    "started_at": self.started_at,
                    "updated": _now_iso(),
                    "text": self.text(),
                })
            except Exception as e:
                logger.warning(f"⚠️ Could not flush partial text: {e}")

    def _build_assistant_message(self, data):
        resp = self.text()
        if self._cancel.is_set():
            resp += "\n\n⏹️ *Generation stopped by user.*"
        if not resp.strip():
            resp = "⚠️ Empty response from the API."

        if self.usage:
            input_tokens = self.usage["input_tokens"]
            output_tokens = self.usage["output_tokens"]
            source_note = "real API tokens"
        else:
            input_tokens = self.input_tokens_est
            output_tokens = estimate_tokens(resp)
            source_note = "estimated tokens"

        self.cost = ClaudeAPI.estimate_cost(self.model, input_tokens, output_tokens)
        data["cost"] = float(data.get("cost") or 0.0) + self.cost
        meta = (
            f"⏱️ Total time: {self.elapsed:.1f}s | "
            f"🔤 {input_tokens:,} in + {output_tokens:,} out ({source_note}) | "
            f"💲 Estimated cost: ${self.cost:.6f} "
            f"(conversation: ${data['cost']:.6f})"
        )
        logger.info(f"✅ Response committed | {self.elapsed:.1f}s | model={self.model} | "
                    f"tokens: {input_tokens}+{output_tokens} | cost: ${self.cost:.6f}")
        return {"role": "assistant", "content": resp, "meta": meta,
                "model": self.model, "created": _now_iso()}

    def _commit(self):
        """Writes the answer into the conversation file. Idempotent; may be called
        from the background thread (normal end) or the main thread (Stop/discard).
        Makes no st.* calls."""
        with self._commit_lock:
            if self.committed:
                return
            self.committed = True
            if self.finished_at is None:
                self.finished_at = time.time()
            try:
                with self.store.lock(self.chat_id):
                    data = self.store.load(self.chat_id)
                    pending = data.get("pending") or {}
                    if pending.get("job_id") == self.job_id:
                        if not self._discard:
                            data["messages"].append(self._build_assistant_message(data))
                        data["pending"] = None
                        self.store.save(self.chat_id, data)
                    else:
                        logger.info(f"🗑️ Job {self.job_id[:8]} discarded "
                                    f"(conversation cleared or deleted)")
                    self.store.delete_partial(self.job_id)
                    self.registry.remove(self.job_id)
            except Exception as e:
                self.commit_error = f"{type(e).__name__}: {e}"
                logger.exception(f"❌ Could not commit job {self.job_id[:8]} to disk")
                self.registry.remove(self.job_id)

    # ---------- public API ----------
    def text(self):
        with self._lock:
            return "".join(self._parts)

    def cancel(self, discard=False):
        """Stop: commits what was generated so far (or nothing, if discard=True)."""
        if discard:
            self._discard = True
        self._cancel.set()
        self._commit()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    @property
    def finished(self):
        return self._done.is_set() or self.committed

    @property
    def elapsed(self):
        return (self.finished_at or time.time()) - self.started_at


def load_chat_with_recovery(chat_id):
    """
    Loads a conversation from disk. Returns (data, live_job).

    If the file says a generation is pending but no live job exists in this
    process (server restarted / crashed), the partial text saved on disk is
    turned into an assistant message, so nothing is silently lost.
    The check runs under the chat lock, the same lock used by job commits.
    """
    with STORE.lock(chat_id):
        data = STORE.load(chat_id)
        pending = data.get("pending")
        if not pending:
            return data, None

        job_id = pending.get("job_id") if isinstance(pending, dict) else None
        job = JOBS.get(job_id)
        if job is not None:
            return data, job

        # Orphan pending job -> recover partial text
        partial = STORE.read_partial(job_id) or {}
        text = partial.get("text", "") or ""
        note = ("⚠️ *Generation was interrupted before the answer could be saved "
                "(server restart, crash or storage error).*")
        if text.strip():
            content = f"{text}\n\n{note}\n*Partial answer recovered from disk.*"
        else:
            content = note
        data["messages"].append({
            "role": "assistant",
            "content": content,
            "meta": (f"♻️ Recovered after interruption | model: {pending.get('model', '?')} | "
                     f"started: {pending.get('started_at', '?')} | "
                     f"{len(text):,} chars saved | cost not tracked"),
            "created": _now_iso(),
        })
        data["pending"] = None
        try:
            STORE.save(chat_id, data)
            STORE.delete_partial(job_id)
        except Exception as e:
            logger.error(f"❌ Could not save recovered chat {chat_id}: {e}")
        logger.warning(f"♻️ Recovered interrupted job {str(job_id)[:8]} in chat {chat_id} "
                       f"({len(text)} chars)")
        return data, None


def open_chat(chat_id):
    """Switches the session to `chat_id`. Must run BEFORE widgets are created
    (it may set the model selector). Never cancels a running job: a detached
    job keeps running and saves its answer to its own conversation."""
    st.session_state.job = None
    data, live_job = load_chat_with_recovery(chat_id)
    st.session_state.chat_id = chat_id
    st.session_state.msgs = data["messages"]
    st.session_state.session_cost = float(data.get("cost") or 0.0)
    if live_job is not None:
        st.session_state.job = live_job  # re-attach to the still-running generation

    if STORE.exists(chat_id):
        saved_model = data.get("model")
        if saved_model in ClaudeAPI.MODELS:
            st.session_state.selected_model = saved_model
            st.session_state.model_selector = saved_model

    try:
        st.query_params["chat"] = chat_id
    except Exception as e:
        logger.debug(f"Could not set query param: {e}")
    logger.info(f"📂 Chat opened: {chat_id} | {len(data['messages'])} messages | "
                f"live job: {live_job is not None}")


def reload_current_chat():
    """Re-reads the current conversation from disk (source of truth)."""
    chat_id = st.session_state.get("chat_id")
    if not chat_id:
        return
    data, live_job = load_chat_with_recovery(chat_id)
    st.session_state.msgs = data["messages"]
    st.session_state.session_cost = float(data.get("cost") or 0.0)
    if live_job is not None and live_job is not st.session_state.get("job"):
        st.session_state.job = live_job


def discard_jobs_for_chat(chat_id):
    """Cancels running jobs of a chat WITHOUT saving their answers (Clear/Delete)."""
    current = st.session_state.get("job")
    if current is not None and current.chat_id == chat_id:
        current.cancel(discard=True)
        st.session_state.job = None
    for job in JOBS.for_chat(chat_id):
        job.cancel(discard=True)


def delete_chat(chat_id):
    discard_jobs_for_chat(chat_id)
    STORE.delete(chat_id)


def resolve_initial_chat_id():
    """URL ?chat=<id> first, then the most recently updated chat, else a new one."""
    qp = st.query_params.get("chat")
    if is_valid_chat_id(qp):
        return qp
    return STORE.most_recent() or new_chat_id()


def render_active_job(slot, live=True):
    """Shows the in-progress answer. Safe to be interrupted by a rerun or by the
    session being destroyed: the job keeps running and saves to disk on its own."""
    job = st.session_state.get("job")
    if job is None:
        return

    with slot:
        with st.chat_message("assistant"):
            if st.button("⏹️ Stop", key="stop_job"):
                job.cancel()
            placeholder = st.empty()
            status = st.empty()
            last_len = -1
            while not job.finished:
                text = job.text()
                if live and text and len(text) != last_len:
                    placeholder.markdown(text + "▌")
                    last_len = len(text)
                phase = "Generating" if text else "Thinking"
                status.caption(f"⏳ {phase}… {job.elapsed:.0f}s | {len(text):,} chars | "
                               f"💾 auto-saved to disk")
                # Throttle: the longer the text, the fewer full re-sends
                time.sleep(min(2.0, 0.25 + len(text) / 100_000))

    st.session_state.job = None
    if job.chat_id == st.session_state.get("chat_id"):
        reload_current_chat()  # the answer was committed to disk by the job
        if st.session_state.get("job") is job:
            st.session_state.job = None
    st.rerun()

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
if 'session_cost' not in st.session_state:
    st.session_state.session_cost = 0.0
if 'job' not in st.session_state:
    st.session_state.job = None
if 'keep_attachments' not in st.session_state:
    st.session_state.keep_attachments = True
if 'uploader_key' not in st.session_state:
    st.session_state.uploader_key = 0

# ============ CONVERSATION SELECTION (must run BEFORE any widget) ============
_pending_open = st.session_state.pop("pending_open", None)
if _pending_open == "__new__":
    open_chat(new_chat_id())
elif _pending_open == "__latest__":
    open_chat(STORE.most_recent() or new_chat_id())
elif _pending_open and is_valid_chat_id(_pending_open):
    open_chat(_pending_open)
elif "chat_id" not in st.session_state:
    open_chat(resolve_initial_chat_id())
else:
    # URL changed (e.g. user pasted another ?chat=<id>)
    _qp_chat = st.query_params.get("chat")
    if is_valid_chat_id(_qp_chat) and _qp_chat != st.session_state.chat_id:
        open_chat(_qp_chat)

# Guard: a legacy model id left in session state would break the selectbox
if st.session_state.selected_model not in ClaudeAPI.MODELS:
    st.session_state.selected_model = DEFAULT_MODEL
if st.session_state.model_selector not in ClaudeAPI.MODELS:
    st.session_state.model_selector = DEFAULT_MODEL

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

    # Model selection (price shown inside the dropdown)
    model = st.selectbox(
        "Model",
        list(ClaudeAPI.MODELS.keys()),
        format_func=lambda x: f"{ClaudeAPI.MODELS[x]} — ${ClaudeAPI.MODEL_PRICES[x]}/MTok",
        key='model_selector'
    )

    if model != st.session_state.selected_model:
        st.session_state.selected_model = model
        st.rerun()

    max_tokens_limit = ClaudeAPI.get_max_tokens(model)
    model_price = ClaudeAPI.get_price(model)
    st.info(
        f"📊 Max tokens: {max_tokens_limit:,}\n\n"
        f"💲 Price: **${model_price}/MTok**"
    )

    # Parameters
    # Temperature slider is shown ONLY for models that still accept the
    # parameter. The allowlist is currently empty, so `temp` stays None and is
    # never included in the API payload.
    if ClaudeAPI.supports_temperature(model):
        temp = st.slider("🌡️ Temperature", 0.0, 1.0, 0.5, 0.1)
    else:
        temp = None
        st.caption("🌡️ Temperature is not supported by the current Claude models "
                   "(the API rejects it). Sampling is handled adaptively.")

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

    # Live cost ceiling for the current settings
    st.caption(
        f"💸 Max output cost for this setting: "
        f"~${max_t / 1_000_000 * model_price:.4f}"
    )

    use_streaming = st.checkbox("🔄 Enable Streaming", value=True,
                                help="See response in real time (recommended for long responses)")

    enable_mermaid = st.checkbox("📊 Enable Mermaid Diagrams", value=st.session_state.enable_mermaid,
                                 help="When enabled, renders Mermaid diagrams visually. When disabled, shows the source code.")
    st.session_state.enable_mermaid = enable_mermaid

    st.checkbox(
        "📎 Keep attachments in context",
        key="keep_attachments",
        help="When enabled, files/images attached earlier in this conversation are re-sent "
             "with every follow-up question, so the model can still 'see' them. "
             "Disable to save tokens (only the typed text of earlier messages is sent).",
    )

    # System Prompt Customization
    with st.expander("📝 System Prompt"):
        st.session_state.system_prompt = st.text_area(
            "Define assistant behavior:",
            value=st.session_state.system_prompt,
            height=100
        )

    # Conversations (auto-saved to disk)
    with st.expander("💬 Conversations"):
        current_id = st.session_state.chat_id
        st.caption(f"💾 Auto-saved to disk · current: `{current_id}`")

        if st.button("🆕 New chat", use_container_width=True):
            st.session_state.pending_open = "__new__"
            st.rerun()

        chats = STORE.list_chats()
        if chats:
            labels = {
                c["id"]: (
                    f"{'▶ ' if c['id'] == current_id else ''}"
                    f"{'⏳ ' if c.get('pending') else ''}"
                    f"{c.get('title', '(untitled)')} · "
                    f"{str(c.get('updated', ''))[:16].replace('T', ' ')}"
                )
                for c in chats
            }
            chat_ids = list(labels.keys())
            selected_chat = st.selectbox(
                "Open conversation:",
                chat_ids,
                index=chat_ids.index(current_id) if current_id in chat_ids else 0,
                format_func=lambda i: labels.get(i, i),
            )
            col1, col2 = st.columns(2)
            with col1:
                if st.button("📂 Open", use_container_width=True,
                             disabled=(selected_chat == current_id)):
                    st.session_state.pending_open = selected_chat
                    st.rerun()
            with col2:
                if st.button("🗑️ Delete", use_container_width=True):
                    st.session_state.delete_armed = selected_chat

            if st.session_state.get("delete_armed") == selected_chat:
                st.warning("Delete this conversation permanently?")
                d1, d2 = st.columns(2)
                with d1:
                    if st.button("✅ Yes, delete", use_container_width=True):
                        delete_chat(selected_chat)
                        st.session_state.pop("delete_armed", None)
                        if selected_chat == current_id:
                            st.session_state.pending_open = "__latest__"
                        st.rerun()
                with d2:
                    if st.button("✖️ Cancel", use_container_width=True):
                        st.session_state.pop("delete_armed", None)
                        st.rerun()
        else:
            st.caption("No saved conversations yet.")

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
            total_tokens = sum(message_context_tokens(m) for m in st.session_state.msgs)

            col1, col2 = st.columns(2)
            col1.metric("Messages", total_msgs)
            col2.metric("Context tokens", f"{total_tokens:,}")

            st.metric("Conversation cost (est.)", f"${st.session_state.session_cost:.6f}")

            if total_msgs > 0:
                df = create_usage_dataframe(st.session_state.msgs)
                st.line_chart(df.set_index('Message')['Cumulative'])
        else:
            st.caption("No messages yet.")

    # Buttons
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ Clear", use_container_width=True):
            chat_id = st.session_state.chat_id
            discard_jobs_for_chat(chat_id)
            if STORE.exists(chat_id):
                STORE.update(chat_id, lambda d: d.update(messages=[], cost=0.0, pending=None))
            st.session_state.msgs = []
            st.session_state.session_cost = 0.0
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
        # Detach only: a running generation still finishes and is saved to disk
        st.session_state.job = None
        cookie_manager = get_cookie_manager()
        cookie_manager.delete(COOKIE_NAME, key="delete_auth_cookie_logout")
        st.session_state.authenticated = False
        for _k in ("chat_id", "msgs", "session_cost"):
            st.session_state.pop(_k, None)
        st.rerun()

    if st.button("ℹ️ About", use_container_width=True):
        st.info(
            f"**Claude Chat** v{APP_VERSION}\n\n"
            f"Default model: `{DEFAULT_MODEL}`\n\n"
            f"Active model: `{st.session_state.selected_model}`\n\n"
            f"Price: `${ClaudeAPI.get_price(st.session_state.selected_model)}/MTok`\n\n"
            f"Temperature: `disabled (unsupported by API)`\n\n"
            f"Storage: `{STORE.root}`"
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

# Slot for the in-progress answer. It is FILLED at the very end of the script,
# so the uploader and chat input below are rendered before the polling loop.
job_slot = st.container()

# File uploader with extended support.
# The key changes after each send, which clears the uploader: files already sent
# live in the conversation history, so they must not be attached again.
files = st.file_uploader(
    "📎 Attach files",
    accept_multiple_files=True,
    type=['png','jpg','jpeg','txt','py','csv','md','json','cfg','php','sql','pdf','js','html','css','xml','yml','yaml','xlsx','docx','ipynb','zip'],
    key=f"uploader_{st.session_state.uploader_key}",
    help="Attachments are saved with the message and kept in context for follow-up questions.",
)

job_active = st.session_state.job is not None

# Chat input (disabled while an answer is being generated)
if prompt := st.chat_input(
    "Type your message..." if not template_prompt else f"[{template}] Type your text here...",
    disabled=job_active,
):
    logger.info(f"📝 User input received | Length: {len(prompt)}")
    chat_id = st.session_state.chat_id

    if template_prompt:
        full_prompt = f"{template_prompt}\n\n{prompt}"
        # Show to user what they typed (without the full template text, to avoid clutter)
        display_prompt = f"**[{template}]**\n\n{prompt}"
    else:
        full_prompt = prompt
        display_prompt = prompt

    # Handle /model command (short synchronous call)
    if prompt.strip().lower() == "/model":
        logger.debug("Executing /model command")
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
                f"💲 **Price:** ${ClaudeAPI.get_price(model)}/MTok\n\n"
                f"{match}"
            )
            logger.info(f"✅ /model command executed | UI: {model} | API: {actual_model}")
        except Exception as e:
            logger.error(f"❌ /model command error: {e}")
            resp = f"❌ Error checking model: {e}"

        _user_msg = {"role": "user", "content": display_prompt,
                     "prompt_text": sanitize_input(full_prompt), "created": _now_iso()}
        _assistant_msg = {"role": "assistant", "content": resp, "created": _now_iso()}
        try:
            _data = STORE.update(chat_id, lambda d: d["messages"].extend([_user_msg, _assistant_msg]))
            st.session_state.msgs = _data["messages"]
        except Exception as e:
            logger.error(f"❌ Could not save /model exchange: {e}")
            st.session_state.msgs.extend([_user_msg, _assistant_msg])
        st.rerun()

    # History = everything BEFORE this new user message, WITH earlier attachments
    history = build_api_history(st.session_state.msgs, st.session_state.keep_attachments)

    # Files are read here, in the main thread (the background thread must not touch st.*)
    content, attached_names, file_errors = st.session_state.api.build_user_content(full_prompt, files)
    if file_errors:
        display_prompt += "\n\n" + "\n".join(f"⚠️ Could not process file {e}" for e in file_errors)

    user_msg = {
        "role": "user",
        "content": display_prompt,                 # what is shown in the UI
        "prompt_text": sanitize_input(full_prompt),  # real prompt (template included)
        "created": _now_iso(),
    }
    if attached_names:
        user_msg["api_content"] = content          # full blocks: text + images + file contents
        user_msg["attachments"] = attached_names

    input_tokens_est = estimate_content_tokens(content) + sum(
        estimate_content_tokens(h["content"]) for h in history
    )

    job = StreamJob(
        store=STORE,
        registry=JOBS,
        chat_id=chat_id,
        api=st.session_state.api,
        content=content,
        model=model,
        temp=temp,
        max_t=max_t,
        history=history,
        system_prompt=st.session_state.system_prompt,
        effort=effort,
        input_tokens_est=input_tokens_est,
    )

    def _start_pending(d):
        d["messages"].append(user_msg)
        d["model"] = model
        d["pending"] = {"job_id": job.job_id, "model": model, "started_at": _now_iso()}

    # Register BEFORE marking the chat as pending on disk, so another session
    # opening this chat never mistakes the job for an orphan.
    JOBS.add(job)
    try:
        data = STORE.update(chat_id, _start_pending)
    except Exception as e:
        JOBS.remove(job.job_id)
        logger.exception("❌ Could not save the user message to disk")
        st.error(f"❌ Could not save the message to disk: {e}")
        st.stop()

    st.session_state.msgs = data["messages"]
    logger.info(f"💬 Starting job {job.job_id[:8]} | Chat: {chat_id} | Model: {model} | "
                f"Streaming: {use_streaming} | Files: {len(attached_names)} | "
                f"History msgs: {len(history)} | Template: {template or 'None'}")
    job.start()
    st.session_state.job = job
    st.session_state.uploader_key += 1  # clear the uploader
    st.rerun()

# Must be the LAST thing in the script (it blocks while polling the job)
render_active_job(job_slot, live=use_streaming)