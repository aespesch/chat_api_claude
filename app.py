import os, streamlit as st, anthropic, base64, warnings
from pathlib import Path
warnings.filterwarnings('ignore')
st.set_page_config(page_title="Claude Chat", page_icon="🤖", layout="wide")

class ClaudeAPI:
    MODELS = {
        "claude-opus-4-1-20250805": "Claude Opus 4.1 (Most Advanced)",
        "claude-3-opus-20240229": "Claude 3 Opus (Most Capable)",
        "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet (Balanced)",
        "claude-3-sonnet-20240229": "Claude 3 Sonnet",
        "claude-3-haiku-20240307": "Claude 3 Haiku (Fastest)"
    }

    def __init__(self):
        api_key = None

        # Primeiro verifica se st.secrets está disponível
        if hasattr(st, 'secrets') and len(st.secrets) > 0:
            try:
                api_key = st.secrets.get("KEY") or st.secrets.get("ANTHROPIC_API_KEY")
            except Exception:
                pass

        # Se não conseguiu do Streamlit, tenta variável de ambiente
        if not api_key:
            api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("KEY")

        # Se não conseguiu, tenta do arquivo local
        if not api_key:
            try:
                import toml
                secrets_path = Path(__file__).parent / ".streamlit" / "secrets.toml"

                if secrets_path.exists():
                    secrets = toml.load(secrets_path)
                    api_key = secrets.get("KEY") or secrets.get("ANTHROPIC_API_KEY")
            except Exception as e:
                st.warning(f"Could not load local secrets: {e}")

        if not api_key:
            st.error("❌ API key not found! Please set it in Streamlit secrets or environment variables.")
            self.client = None
        else:
            try:
                # Inicialização simplificada sem parâmetros problemáticos
                self.client = anthropic.Anthropic(api_key=api_key)
            except Exception as e:
                st.error(f"❌ Error initializing Claude API: {str(e)}")
                self.client = None

    def send_message(self, msg, model, temp=0.7, max_t=2000, hist=None, files=None):
        if not self.client: 
            return "❌ API key not configured"

        content = [{"type": "text", "text": msg}]

        if files:
            for f in files:
                try:
                    if f.type.startswith('image/'): 
                        content.append({
                            "type": "image", 
                            "source": {
                                "type": "base64", 
                                "media_type": f.type, 
                                "data": base64.b64encode(f.read()).decode()
                            }
                        })
                    elif f.name.endswith(('.txt','.py','.csv','.md','.json')):
                        text_content = f.read().decode('utf-8', errors='ignore')
                        content.append({
                            "type": "text", 
                            "text": f"\n📄 {f.name}:\n```\n{text_content}\n```"
                        })
                except Exception as e:
                    st.warning(f"Could not process file {f.name}: {e}")

        msgs = (hist or []) + [{"role": "user", "content": content}]

        try: 
            response = self.client.messages.create(
                model=model, 
                max_tokens=max_t, 
                temperature=temp, 
                messages=msgs
            )
            return response.content[0].text
        except Exception as e: 
            return f"❌ Error: {str(e)}"

# Initialize session state
if 'msgs' not in st.session_state: 
    st.session_state.msgs = []
if 'api' not in st.session_state: 
    st.session_state.api = ClaudeAPI()

# Sidebar
with st.sidebar:
    st.title("⚙️ Settings")

    # Model selection
    model = st.selectbox(
        "Model", 
        list(ClaudeAPI.MODELS.keys()), 
        format_func=lambda x: ClaudeAPI.MODELS[x]
    )

    # Parameters
    temp = st.slider("Temperature", 0.0, 1.0, 0.7, 0.1)
    max_t = st.slider("Max Tokens", 100, 4000, 2000, 100)

    # Buttons
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ Clear", use_container_width=True): 
            st.session_state.msgs = []
            st.rerun()
    with col2:
        if st.button("📋 Copy", use_container_width=True):
            if st.session_state.msgs:
                chat_text = "\n\n".join([
                    f"**{m['role'].title()}**: {m['content']}" 
                    for m in st.session_state.msgs
                ])
                st.text_area("Copy this text:", chat_text, height=200)
                st.info("Select all text above and copy manually (Ctrl+C)")
            else: 
                st.warning("No messages to copy")

# Main chat interface
st.title("🤖 Claude Chat")

# Display chat history
for m in st.session_state.msgs: 
    st.chat_message(m["role"]).markdown(m["content"])

# File uploader
files = st.file_uploader(
    "📎 Attach files", 
    accept_multiple_files=True, 
    type=['png','jpg','jpeg','txt','py','csv','md','json']
)

# Chat input
if prompt := st.chat_input("Type your message..."):
    # Add user message to history
    st.session_state.msgs.append({"role": "user", "content": prompt})
    st.chat_message("user").markdown(prompt)

    # Get and display assistant response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            # Prepare history for API
            history = [
                {"role": m["role"], "content": m["content"]} 
                for m in st.session_state.msgs[:-1]
            ]

            # Send message
            resp = st.session_state.api.send_message(
                prompt, model, temp, max_t, history, files
            )

        st.markdown(resp)
        st.session_state.msgs.append({"role": "assistant", "content": resp})
