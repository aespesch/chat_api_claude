import os, streamlit as st, anthropic, base64, warnings, paperclip
from pathlib import Path
warnings.filterwarnings('ignore')
st.set_page_config(page_title="Claude Chat", page_icon="🤖", layout="wide")

class ClaudeAPI:
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
        api_key = None

        # Primeiro verifica se st.secrets está disponível
        if hasattr(st, 'secrets') and len(st.secrets) > 0:
            try:
                api_key = st.secrets["KEY"]
            except KeyError:
                pass  # Chave específica não existe

        # Se não conseguiu do Streamlit, tenta do arquivo local
        if not api_key:
            try:
                import toml
                secrets_path = Path(__file__).parent.parent / "chat_api_claude.streamlit" / "secrets.toml"
                if not secrets_path.exists():
                    secrets_path = Path("D:/USER/Toni/Cursos/LLM/Claude/chat_api_claude.streamlit/secrets.toml")

                if secrets_path.exists():
                    secrets = toml.load(secrets_path)
                    api_key = secrets.get("KEY")  # Usar .get() para evitar KeyError
                else:
                    st.warning("No secrets found")
            except Exception as e:
                st.error(f"Error loading secrets: {e}")

        if not api_key:
            st.error("❌ API key not found!")

        self.client = anthropic.Anthropic(api_key=api_key) if api_key else None

    def send_message(self, msg, model, temp=0.7, max_t=2000, hist=None, files=None):
        if not self.client: return "❌ API key not configured"
        content = [{"type": "text", "text": msg}]
        if files:
            for f in files:
                if f.type.startswith('image/'): content.append({"type": "image", "source": {"type": "base64", "media_type": f.type, "data": base64.b64encode(f.read()).decode()}})
                elif f.name.endswith(('.txt','.py','.csv','.md','.json')): content.append({"type": "text", "text": f"\n{f.name}:\n```{f.read().decode()}\n```"})
        msgs = (hist or []) + [{"role": "user", "content": content}]
        try: return self.client.messages.create(model=model, max_tokens=max_t, temperature=temp, messages=msgs).content[0].text
        except Exception as e: return f"❌ Error: {str(e)}"

if 'msgs' not in st.session_state: st.session_state.msgs = []
if 'api' not in st.session_state: st.session_state.api = ClaudeAPI()

with st.sidebar:
    st.title("⚙️ Settings")
    model = st.selectbox("Model", list(ClaudeAPI.MODELS.keys()), format_func=lambda x: ClaudeAPI.MODELS[x])
    temp = st.slider("Temperature", 0.0, 1.0, 0.7, 0.1)
    max_t = st.slider("Max Tokens", 100, 4000, 2000, 100)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ Clear", use_container_width=True): st.session_state.msgs = []; st.rerun()
    with col2:
        if st.button("📋 Copy", use_container_width=True):
            if st.session_state.msgs:
                chat_text = "\n\n".join([f"{m['role'].title()}: {m['content']}" for m in st.session_state.msgs])
                try:
                    pyperclip.copy(chat_text)
                    st.success("✅ Chat copied to clipboard!")
                except:
                    # Fallback se pyperclip não funcionar
                    st.text_area("Copy this text:", chat_text, height=200)
                    st.info("Select all text above and copy manually (Ctrl+C)")
            else: 
                st.warning("No messages to copy")

st.title("🤖 Claude Chat")
for m in st.session_state.msgs: st.chat_message(m["role"]).markdown(m["content"])

files = st.file_uploader("📎 Files", accept_multiple_files=True, type=['png','jpg','jpeg','txt','py','csv','md','json'])
if prompt := st.chat_input("Message..."):
    st.session_state.msgs.append({"role": "user", "content": prompt})
    st.chat_message("user").markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            resp = st.session_state.api.send_message(prompt, model, temp, max_t, [{"role": m["role"], "content": m["content"]} for m in st.session_state.msgs[:-1]], files)
        st.markdown(resp)
        st.session_state.msgs.append({"role": "assistant", "content": resp})