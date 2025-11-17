import os, streamlit as st, anthropic, base64, warnings
from pathlib import Path
warnings.filterwarnings('ignore')
st.set_page_config(page_title="Claude Chat", page_icon="🤖", layout="wide")

class ClaudeAPI:
    MODELS = {
        # Modelos Mais Recentes e Recomendados (Claude 4.5)
        "claude-sonnet-4-5-20250929": "Claude Sonnet 4.5 (Mais Inteligente para Agentes e Codificação)",
        "claude-haiku-4-5-20251001": "Claude Haiku 4.5 (Mais Rápido, Inteligência Próxima à Fronteira)",
        "claude-opus-4-1-20250805": "Claude Opus 4.1 (Excepcional para Raciocínio Especializado)",

        # Modelos Legados (Ainda Disponíveis)
        "claude-sonnet-4-20250514": "Claude Sonnet 4 (Legado)",
        "claude-3-7-sonnet-20250219": "Claude 3.7 Sonnet (Legado)",
        "claude-opus-4-20250514": "Claude Opus 4 (Legado)",
        "claude-3-5-haiku-20241022": "Claude 3.5 Haiku (Legado)",
        "claude-3-haiku-20240307": "Claude 3 Haiku (Legado)",
    }

    # Definir limites máximos de tokens por modelo
    MODEL_MAX_TOKENS = {
        "claude-sonnet-4-5-20250929": 64000,
        "claude-haiku-4-5-20251001": 64000,
        "claude-opus-4-1-20250805": 64000,
        "claude-sonnet-4-20250514": 8192,
        "claude-3-7-sonnet-20250219": 8192,
        "claude-opus-4-20250514": 16384,
        "claude-3-5-haiku-20241022": 8192,
        "claude-3-haiku-20240307": 4096,
    }

    @classmethod
    def get_max_tokens(cls, model):
        """Retorna o limite máximo de tokens para um modelo específico"""
        return cls.MODEL_MAX_TOKENS.get(model, 4000)

    def __init__(self):
        api_key = None

        # Primeiro verifica se st.secrets está disponível
        if hasattr(st, 'secrets') and len(st.secrets) > 0:
            try:
                api_key = st.secrets.get("KEY")
            except Exception:
                pass

        # Se não conseguiu do Streamlit, tenta variável de ambiente
        if not api_key:
            api_key = os.getenv("KEY")

        # Se não conseguiu, tenta do arquivo local
        if not api_key:
            try:
                import toml
                secrets_path = Path(__file__).parent / ".streamlit" / "secrets.toml"

                if secrets_path.exists():
                    secrets = toml.load(secrets_path)
                    api_key = secrets.get("KEY")
            except Exception as e:
                st.warning(f"Could not load local secrets: {e}")

        if not api_key:
            st.error("❌ API key not found! Please set it in Streamlit secrets or environment variables.")
            self.client = None
        else:
            try:
                self.client = anthropic.Anthropic(api_key=api_key)
            except Exception as e:
                st.error(f"❌ Error initializing Claude API: {str(e)}")
                self.client = None

    def extract_text_from_pdf(self, pdf_file):
        """Extrai texto de um arquivo PDF"""
        try:
            import PyPDF2
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            text = ""
            for page_num, page in enumerate(pdf_reader.pages, 1):
                page_text = page.extract_text()
                text += f"\n--- Página {page_num} ---\n{page_text}\n"
            return text
        except ImportError:
            st.error("❌ PyPDF2 não está instalado. Execute: pip install PyPDF2")
            return None
        except Exception as e:
            st.error(f"❌ Erro ao processar PDF: {str(e)}")
            return None

    def send_message_stream(self, msg, model, temp=0.7, max_t=2000, hist=None, files=None):
        """Versão com streaming que retorna um generator"""
        if not self.client: 
            yield "❌ API key not configured"
            return

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
                    elif f.name.endswith('.pdf'):
                        # Processar arquivo PDF
                        pdf_text = self.extract_text_from_pdf(f)
                        if pdf_text:
                            content.append({
                                "type": "text", 
                                "text": f"\n📄 {f.name} (PDF):\n```\n{pdf_text}\n```"
                            })
                        else:
                            st.warning(f"Não foi possível extrair texto de {f.name}")
                    elif f.name.endswith(('.txt','.py','.csv','.md','.json','.php','.cfg','.sql')):
                        text_content = f.read().decode('utf-8', errors='ignore')
                        if f.name.endswith('.php'):
                            lang = 'php'
                        elif f.name.endswith('.sql'):
                            lang = 'sql'
                        else:
                            lang = ''
                        content.append({
                            "type": "text", 
                            "text": f"\n📄 {f.name}:\n```{lang}\n{text_content}\n```"
                        })
                except Exception as e:
                    st.warning(f"Could not process file {f.name}: {e}")

        msgs = (hist or []) + [{"role": "user", "content": content}]

        try: 
            # Usar stream=True para habilitar streaming
            with self.client.messages.stream(
                model=model, 
                max_tokens=max_t, 
                temperature=temp, 
                messages=msgs
            ) as stream:
                for text in stream.text_stream:
                    yield text

        except anthropic.BadRequestError as e:
            yield f"❌ Bad Request: {str(e)} - Model might not exist or be accessible"
        except Exception as e: 
            yield f"❌ Error: {str(e)}"

# Initialize session state
if 'msgs' not in st.session_state: 
    st.session_state.msgs = []
if 'api' not in st.session_state: 
    st.session_state.api = ClaudeAPI()
if 'selected_model' not in st.session_state:
    st.session_state.selected_model = list(ClaudeAPI.MODELS.keys())[0]

# Sidebar
with st.sidebar:
    st.title("⚙️ Settings")

    # Model selection
    model = st.selectbox(
        "Model", 
        list(ClaudeAPI.MODELS.keys()), 
        format_func=lambda x: ClaudeAPI.MODELS[x],
        key='model_selector'
    )

    # Atualizar modelo selecionado no session state
    if model != st.session_state.selected_model:
        st.session_state.selected_model = model
        st.rerun()

    # Obter limite máximo para o modelo selecionado
    max_tokens_limit = ClaudeAPI.get_max_tokens(model)

    # Mostrar informação sobre o limite
    st.info(f"📊 Max tokens for this model: {max_tokens_limit:,}")

    # Parameters
    temp = st.slider("Temperature", 0.0, 1.0, 0.5, 0.1)
    max_t = st.slider(
        "Max Tokens", 
        100, 
        max_tokens_limit, 
        min(8000, max_tokens_limit),  # Valor padrão aumentado
        100
    )

    # Toggle para streaming
    use_streaming = st.checkbox("🔄 Enable Streaming", value=True, 
                                help="Ver resposta em tempo real (recomendado para respostas longas)")

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

# File uploader - ADICIONADO 'pdf' AOS TIPOS ACEITOS
files = st.file_uploader(
    "📎 Attach files", 
    accept_multiple_files=True, 
    type=['png','jpg','jpeg','txt','py','csv','md','json','cfg','php','sql','pdf']
)

# Chat input
if prompt := st.chat_input("Type your message..."):
    # Add user message to history
    st.session_state.msgs.append({"role": "user", "content": prompt})
    st.chat_message("user").markdown(prompt)

    # Get and display assistant response
    with st.chat_message("assistant"):
        # Prepare history for API
        history = [
            {"role": m["role"], "content": m["content"]} 
            for m in st.session_state.msgs[:-1]
        ]

        if use_streaming:
            # Streaming mode - mostra resposta em tempo real
            message_placeholder = st.empty()
            full_response = ""

            for chunk in st.session_state.api.send_message_stream(
                prompt, model, temp, max_t, history, files
            ):
                full_response += chunk
                message_placeholder.markdown(full_response + "▌")

            message_placeholder.markdown(full_response)
            resp = full_response
        else:
            # Modo tradicional (mantido para compatibilidade)
            with st.spinner("Thinking..."):
                # Usar a função de streaming mas coletar tudo
                full_response = ""
                for chunk in st.session_state.api.send_message_stream(
                    prompt, model, temp, max_t, history, files
                ):
                    full_response += chunk
                resp = full_response

            st.markdown(resp)

        st.session_state.msgs.append({"role": "assistant", "content": resp})