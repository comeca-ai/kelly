import streamlit as st
from streamlit_option_menu import option_menu # For a nicer sidebar menu
import firebase_admin
from firebase_admin import credentials, firestore, auth as firebase_auth
from google.cloud.firestore_v1.base_query import FieldFilter
import requests
import datetime
import os
from dotenv import load_dotenv
from fpdf import FPDF
import time
import uuid # For generating unique user IDs if needed

# Load environment variables from .env file for local development
load_dotenv()

# --- Configuration ---
APP_ID = os.getenv("APP_ID", "default-ai-content-tool-v2")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Firebase Initialization ---
# Ensure GOOGLE_APPLICATION_CREDENTIALS is set in your environment or .env file
try:
    if not firebase_admin._apps:
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not cred_path:
            st.error("GOOGLE_APPLICATION_CREDENTIALS environment variable not set.")
            st.stop()
        if not os.path.exists(cred_path):
            st.error(f"Firebase credentials file not found at: {cred_path}")
            st.stop()
        
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    st.error(f"Error initializing Firebase: {e}")
    # Mock db for UI development if Firebase fails (optional)
    class MockDB:
        def collection(self, name): return self
        def document(self, id=None): return self
        def get(self): return MockDocSnapshot()
        def stream(self): return []
        def add(self, data): return None, MockDocRef()
        def update(self, data): return None
        def delete(self): return None
        def order_by(self, field, direction): return self
        def limit(self, num): return self
        def start_after(self, doc_snapshot): return self
        def where(self, field_path=None, op_string=None, value=None, filter=None): return self


    class MockDocRef:
        id = "mock_id"
    
    class MockDocSnapshot:
        exists = False
        id = "mock_id"
        def to_dict(self): return {}

    if 'db' not in locals(): # only if db was not initialized
        db = MockDB()
        st.warning("Using mock Firebase database due to initialization error.")


# --- Tool Configurations (Ported from JS) ---
tool_configs = {
  'article': { 'id': 'article', 'name': "Gerador de Artigos", 'description': "Crie artigos completos a partir de um tema ou palavras-chave.", 'promptPlaceholder': "Ex: O futuro da inteligência artificial no jornalismo investigativo", 'icon': '📄', 'apiPromptPrefix': "Escreva um artigo detalhado, informativo e bem estruturado sobre o seguinte tema: ", 'sampleOutput': "Artigo gerado sobre o tema X...", },
  'headline': { 'id': 'headline', 'name': "Gerador de Headlines", 'description': "Crie headlines chamativas e persuasivas para seus conteúdos.", 'promptPlaceholder': "Ex: Artigo sobre o impacto das redes sociais na política brasileira", 'icon': '📰', 'apiPromptPrefix': "Gere 5 opções de headlines criativas e impactantes para um conteúdo sobre: ", 'sampleOutput': "1. Headline A\n2. Headline B...", },
  'social': { 'id': 'social', 'name': "Posts para Redes Sociais", 'description': "Crie posts para diversas redes sociais (Facebook, Instagram, Twitter).", 'promptPlaceholder': "Ex: Lançamento de novo produto eco-friendly para o Instagram", 'icon': '📱', 'apiPromptPrefix': "Crie um post para redes sociais (adequado para Instagram, Facebook e Twitter) sobre: ", 'sampleOutput': "Post para redes sociais sobre Y...", },
  'summary': { 'id': 'summary', 'name': "Resumidor de Conteúdos", 'description': "Resuma textos longos de forma rápida e eficiente.", 'promptPlaceholder': "Cole aqui o texto que você deseja resumir...", 'icon': '✍️', 'apiPromptPrefix': "Faça um resumo conciso e informativo do seguinte texto: ", 'sampleOutput': "Resumo do texto Z...", },
}
popular_tools_ids = ['article', 'headline', 'social', 'summary']
ITEMS_PER_PAGE = 5

# --- Helper Functions ---
def add_toast(message, type='info'):
    if type == 'success':
        st.success(message, icon="✅")
    elif type == 'error':
        st.error(message, icon="🚨")
    elif type == 'warning':
        st.warning(message, icon="⚠️")
    else:
        st.info(message, icon="ℹ️")
    # Streamlit's native st.toast appears at the bottom right by default
    # st.toast(message, icon=icon_map.get(type)) # for actual toast component if preferred

def get_user_id():
    # Simplified user management for Streamlit
    # In a real app, use streamlit-authenticator or similar
    if "user_id" not in st.session_state or not st.session_state.user_id:
        # For this example, let's assign a stable anonymous ID or prompt for one
        # st.session_state.user_id = "anonymous_streamlit_user_" + str(uuid.uuid4()) # Generates a new one each session if not careful
        if "temp_user_id" not in st.session_state:
             st.session_state.temp_user_id = "default_user" # More stable for demo
        st.session_state.user_id = st.session_state.temp_user_id
        st.session_state.user_display_name = "Usuário Visitante" #
    return st.session_state.user_id

def get_user_display_name():
    get_user_id() # ensure user_id and display_name are initialized
    return st.session_state.user_display_name


def download_as_txt(text, filename='conteudo.txt'):
    return st.download_button(
        label="📥 Baixar .txt",
        data=text,
        file_name=filename,
        mime='text/plain',
        key=f"txt_dl_{filename}_{time.time()}" # Unique key
    )

def download_as_pdf(text, filename='conteudo.pdf'):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12) # Basic font, FPDF has limited Unicode support by default
                                   # For full Unicode, you might need to add a specific font like DejaVu
        
        # Attempt to encode to latin-1, replacing unsupported characters
        # This is a common workaround for basic FPDF. For better results, consider reportlab or ensure font supports chars.
        text_encoded = text.encode('latin-1', 'replace').decode('latin-1')
        
        for line in text_encoded.split('\n'):
            pdf.multi_cell(0, 10, line)
        
        pdf_output = pdf.output(dest='S').encode('latin-1') # Get as bytes
        
        st.download_button(
            label="📥 Baixar .pdf",
            data=pdf_output,
            file_name=filename,
            mime='application/pdf',
            key=f"pdf_dl_{filename}_{time.time()}" # Unique key
        )
        add_toast('PDF pronto para download!', 'success')
    except Exception as e:
        st.error(f"Erro ao gerar PDF: {e}")
        add_toast('Erro ao gerar PDF.', 'error')


# --- Firestore Interaction Functions ---
def get_content_collection_ref():
    user_id = get_user_id()
    return db.collection(f"artifacts/{APP_ID}/users/{user_id}/generated_content")

def save_content_to_firestore(content_data):
    user_id = get_user_id()
    if not user_id:
        add_toast("Usuário não identificado. Não é possível salvar.", "error")
        return
    try:
        content_data["createdAt"] = firestore.SERVER_TIMESTAMP
        content_collection = get_content_collection_ref()
        content_collection.add(content_data)
        add_toast("Conteúdo salvo com sucesso!", "success")
        # Trigger rerun or update local list if needed
        if 'generated_content_list' in st.session_state: # Invalidate cache
            del st.session_state['generated_content_list']
        st.rerun()

    except Exception as e:
        print(f"Erro ao salvar conteúdo no Firestore: {e}")
        add_toast(f"Falha ao salvar conteúdo: {e}", "error")

def fetch_content(limit_num=ITEMS_PER_PAGE, last_doc_snapshot=None):
    user_id = get_user_id()
    if not user_id:
        return [], None, False
    
    content_collection = get_content_collection_ref()
    query = content_collection.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit_num)
    if last_doc_snapshot:
        query = query.start_after(last_doc_snapshot)
    
    try:
        docs_snapshots = list(query.stream())
        content = []
        for doc_snap in docs_snapshots:
            item = doc_snap.to_dict()
            item['id'] = doc_snap.id
            if 'createdAt' in item and hasattr(item['createdAt'], 'isoformat'): # Check if it's a datetime object
                 # Convert to user's local timezone if needed, or keep as UTC. For simplicity, use as is.
                pass # Firestore timestamps are timezone-aware (UTC)
            content.append(item)
        
        new_last_doc = docs_snapshots[-1] if docs_snapshots else None
        has_more = len(docs_snapshots) == limit_num
        return content, new_last_doc, has_more
    except Exception as e:
        st.error(f"Erro ao buscar conteúdos: {e}")
        return [], None, False


def delete_content_from_firestore(content_id):
    user_id = get_user_id()
    if not user_id:
        add_toast("Usuário não identificado. Não é possível excluir.", "error")
        return
    try:
        doc_ref = get_content_collection_ref().document(content_id)
        doc_ref.delete()
        add_toast("Conteúdo excluído com sucesso!", "success")
        if 'generated_content_list' in st.session_state: # Invalidate cache
            del st.session_state['generated_content_list']
        st.rerun()

    except Exception as e:
        print(f"Erro ao excluir conteúdo: {e}")
        add_toast(f"Falha ao excluir conteúdo: {e}", "error")

def update_content_in_firestore(content_id, updated_data):
    user_id = get_user_id()
    if not user_id:
        add_toast("Usuário não identificado. Não é possível atualizar.", "error")
        return False
    try:
        updated_data["updatedAt"] = firestore.SERVER_TIMESTAMP
        doc_ref = get_content_collection_ref().document(content_id)
        doc_ref.update(updated_data)
        add_toast("Conteúdo atualizado com sucesso!", "success")
        if 'generated_content_list' in st.session_state: # Invalidate cache
            del st.session_state['generated_content_list']
        return True
    except Exception as e:
        print(f"Erro ao atualizar conteúdo: {e}")
        add_toast(f"Falha ao atualizar conteúdo: {e}", "error")
        return False


# --- Page Rendering Functions ---

def render_dashboard_page():
    st.title(f"Olá, {get_user_display_name()}! 👋")
    st.subheader("Bem-vindo(a) de volta! O que vamos criar hoje?")
    st.markdown("### Ferramentas Mais Populares")

    cols = st.columns(2) # Adjust number of columns as needed
    col_idx = 0
    for tool_id in popular_tools_ids:
        tool = tool_configs[tool_id]
        with cols[col_idx % len(cols)]:
            with st.container(border=True):
                st.subheader(f"{tool['icon']} {tool['name']}")
                st.caption(tool['description'])
                if st.button(f"Acessar {tool['name']}", key=f"dash_btn_{tool_id}", use_container_width=True):
                    st.session_state.current_page = f"tool/{tool_id}"
                    st.rerun()
        col_idx += 1

def render_tool_page(tool_key):
    tool = tool_configs.get(tool_key)
    if not tool:
        st.error("Ferramenta não encontrada.")
        return

    st.title(f"{tool['icon']} {tool['name']}")
    st.caption(tool['description'])

    with st.form(key=f"tool_form_{tool_key}"):
        prompt = st.text_area(
            "Seu Prompt:",
            placeholder=tool['promptPlaceholder'],
            height=150,
            key=f"prompt_{tool_key}"
        )
        submit_button = st.form_submit_button(label="🚀 Gerar Conteúdo", use_container_width=True)

    if 'error_message' in st.session_state and st.session_state.error_message:
        st.error(st.session_state.error_message)
        del st.session_state.error_message


    if submit_button:
        if not prompt.strip():
            st.session_state.error_message = "Por favor, insira um prompt."
            st.rerun()
        
        st.session_state.error_message = ""
        st.session_state.generated_result = ""
        st.session_state.is_loading = True
        st.rerun() # Re-run to show spinner immediately

    if st.session_state.get('is_loading', False):
        with st.spinner("Gerando conteúdo... Por favor, aguarde."):
            full_prompt = f"{tool['apiPromptPrefix']}{st.session_state[f'prompt_{tool_key}']}" # Use the stored prompt
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}" # Updated model
            payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
            
            try:
                response = requests.post(api_url, json=payload, headers={'Content-Type': 'application/json'})
                response.raise_for_status() # Raise an exception for bad status codes
                result = response.json()

                if result.get("candidates") and result["candidates"][0].get("content", {}).get("parts"):
                    text_parts = [part.get("text", "") for part in result["candidates"][0]["content"]["parts"]]
                    st.session_state.generated_result = "".join(text_parts)
                    add_toast('Conteúdo gerado com sucesso!', 'success')
                else:
                    finish_reason = result.get("candidates", [{}])[0].get("finishReason", "N/A")
                    safety_ratings = result.get("candidates", [{}])[0].get("safetyRatings", [])
                    detailed_error = f"Resposta da API vazia ou malformada. Motivo: {finish_reason}. Classificações: {safety_ratings}"
                    print("Estrutura de resposta inesperada:", result)
                    st.session_state.generated_result = f"Não foi possível gerar o conteúdo. {detailed_error}"
                    add_toast(f"Falha ao gerar: {detailed_error}", 'error')
            except requests.exceptions.RequestException as e:
                st.session_state.error_message = f"Erro de rede/API: {e}"
                st.session_state.generated_result = tool.get('sampleOutput', "Ocorreu um erro ao gerar o conteúdo.")
                add_toast(f"Erro na geração (rede): {e}", 'error')
            except Exception as e:
                st.session_state.error_message = f"Erro ao gerar conteúdo: {e}"
                st.session_state.generated_result = tool.get('sampleOutput', "Ocorreu um erro ao gerar o conteúdo.")
                add_toast(f"Erro na geração: {e}", 'error')
            finally:
                st.session_state.is_loading = False
        st.rerun() # Re-run to display results and remove spinner

    if 'generated_result' in st.session_state and st.session_state.generated_result:
        st.subheader("Resultado Gerado:")
        st.text_area("", value=st.session_state.generated_result, height=300, disabled=True, key=f"result_area_{tool_key}")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            # Copy to clipboard is a browser feature, Streamlit can't directly do it.
            # We can show a button that, if clicked, a user can manually copy.
            # Or display it in a way that's easy to copy.
            # For simplicity, direct copy button is omitted. User can select from text_area.
            st.markdown("<small>Selecione e copie o texto acima.</small>", unsafe_allow_html=True)
        with col2:
            download_as_txt(st.session_state.generated_result, f"{tool['id']}_conteudo.txt")
        with col3:
            download_as_pdf(st.session_state.generated_result, f"{tool['id']}_conteudo.pdf")
        with col4:
            if st.button("💾 Salvar Conteúdo", key=f"save_btn_{tool_key}", use_container_width=True):
                if st.session_state.generated_result:
                    content_to_save = {
                        'toolId': tool['id'],
                        'toolName': tool['name'],
                        'prompt': st.session_state.get(f"prompt_{tool_key}", ""), # Get the prompt used
                        'text': st.session_state.generated_result,
                    }
                    save_content_to_firestore(content_to_save)
                else:
                    add_toast("Nenhum conteúdo gerado para salvar.", "warning")


def render_my_content_page():
    st.title("💾 Meus Conteúdos Salvos")

    # Initialize session state for content list, last doc, and has_more
    if 'generated_content_list' not in st.session_state:
        st.session_state.generated_content_list = []
        st.session_state.last_doc_snapshot = None
        st.session_state.has_more_content = True
        st.session_state.is_loading_content = True # Trigger initial load
    
    if st.session_state.get('is_loading_content', True) and not st.session_state.generated_content_list:
        with st.spinner("Carregando seus conteúdos..."):
            content, last_doc, has_more = fetch_content(ITEMS_PER_PAGE)
            st.session_state.generated_content_list = content
            st.session_state.last_doc_snapshot = last_doc
            st.session_state.has_more_content = has_more
            st.session_state.is_loading_content = False
            st.rerun()


    if not st.session_state.generated_content_list and not st.session_state.get('is_loading_content', False):
        st.info("Nenhum conteúdo salvo ainda. Comece a gerar conteúdos e eles aparecerão aqui!")
        return

    for i, item in enumerate(st.session_state.generated_content_list):
        tool_name = item.get('toolName', 'Desconhecido')
        tool_icon = tool_configs.get(item.get('toolId', ''), {}).get('icon', '📝')
        
        # Format createdAt timestamp
        created_at_display = "Data antiga"
        created_at_obj = item.get('createdAt')
        if created_at_obj:
            if isinstance(created_at_obj, datetime.datetime):
                # If it's already a Python datetime (e.g., after Firestore conversion)
                dt_object = created_at_obj
            elif hasattr(created_at_obj, 'seconds'): # Firestore Timestamp
                 dt_object = datetime.datetime.fromtimestamp(created_at_obj.seconds, tz=datetime.timezone.utc).astimezone()
            else: # Fallback for unexpected type
                dt_object = None

            if dt_object:
                 created_at_display = dt_object.strftime('%d/%m/%Y %H:%M')


        with st.expander(f"{tool_icon} {tool_name} - {created_at_display}", expanded=False):
            st.caption(f"Prompt: \"{item.get('prompt', 'N/A')}\"")
            st.markdown(f"```text\n{item.get('text', '')}\n```")
            
            c1, c2, c3, c4 = st.columns([2,2,1,1])
            with c1:
                download_as_txt(item.get('text', ''), f"{tool_name.replace(' ', '_')}_{item['id']}.txt")
            with c2:
                download_as_pdf(item.get('text', ''), f"{tool_name.replace(' ', '_')}_{item['id']}.pdf")
            with c3:
                if st.button("✏️ Editar", key=f"edit_{item['id']}", use_container_width=True):
                    st.session_state.editing_item_id = item['id']
                    st.session_state.editing_item_prompt = item.get('prompt', '')
                    st.session_state.editing_item_text = item.get('text', '')
                    st.session_state.editing_item_toolName = tool_name
                    # No direct modal, we will render the edit form below or use st.dialog
                    # For now, let's just set state and you'd handle dialog display logic
                    st.rerun() # Will show the dialog if conditions met
            with c4:
                if st.button("🗑️ Excluir", key=f"delete_{item['id']}", use_container_width=True):
                    st.session_state.deleting_item_id = item['id']
                    # st.rerun() # Will show the dialog if conditions met

    # Edit Dialog Logic (using st.dialog)
    if 'editing_item_id' in st.session_state and st.session_state.editing_item_id:
        item_id = st.session_state.editing_item_id
        
        @st.dialog(f"Editar Conteúdo: {st.session_state.editing_item_toolName}")
        def edit_modal():
            current_prompt = st.text_area("Prompt Original:", value=st.session_state.editing_item_prompt, height=100, key=f"edit_prompt_{item_id}")
            current_text = st.text_area("Conteúdo Gerado:", value=st.session_state.editing_item_text, height=200, key=f"edit_text_{item_id}")
            
            save_col, cancel_col = st.columns(2)
            if save_col.button("Salvar Alterações", key=f"save_edit_{item_id}", use_container_width=True):
                if not current_text.strip():
                    add_toast("O conteúdo não pode estar vazio.", "error")
                else:
                    success = update_content_in_firestore(item_id, {'prompt': current_prompt, 'text': current_text})
                    if success:
                        del st.session_state.editing_item_id # Close dialog on success
                        st.rerun()
            if cancel_col.button("Cancelar", key=f"cancel_edit_{item_id}", use_container_width=True):
                del st.session_state.editing_item_id
                st.rerun()
        
        # Call the dialog function to display it
        edit_modal()


    # Delete Confirmation Dialog Logic (using st.dialog)
    if 'deleting_item_id' in st.session_state and st.session_state.deleting_item_id:
        item_id_to_delete = st.session_state.deleting_item_id

        @st.dialog("Confirmar Exclusão")
        def confirm_delete_modal():
            st.warning("Tem certeza de que deseja excluir este item? Esta ação não pode ser desfeita.")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Sim, Excluir", type="primary", key=f"confirm_del_btn_{item_id_to_delete}", use_container_width=True):
                delete_content_from_firestore(item_id_to_delete)
                del st.session_state.deleting_item_id # Close dialog
                st.rerun()
            if cancel_col.button("Cancelar", key=f"cancel_del_btn_{item_id_to_delete}", use_container_width=True):
                del st.session_state.deleting_item_id # Close dialog
                st.rerun()
        
        confirm_delete_modal()


    if st.session_state.get('has_more_content', False) and not st.session_state.get('is_loading_content', False):
        if st.button("Carregar Mais Conteúdos", key="load_more_my_content", use_container_width=True):
            st.session_state.is_loading_content = True
            with st.spinner("Carregando mais..."):
                new_content, new_last_doc, new_has_more = fetch_content(
                    ITEMS_PER_PAGE, 
                    st.session_state.last_doc_snapshot
                )
                st.session_state.generated_content_list.extend(new_content)
                st.session_state.last_doc_snapshot = new_last_doc if new_last_doc else st.session_state.last_doc_snapshot
                st.session_state.has_more_content = new_has_more
            st.session_state.is_loading_content = False
            st.rerun()
    elif st.session_state.get('is_loading_content', False):
        st.spinner("Carregando...")


# --- Main App Logic ---
st.set_page_config(layout="wide", page_title="Conteúdo IA")

# Initialize session state variables if they don't exist
default_session_state = {
    "current_page": "dashboard",
    "is_loading": False,
    "generated_result": "",
    "error_message": "",
    "user_id": None, # Will be set by get_user_id()
    "user_display_name": "Usuário",
    "generated_content_list": [],
    "last_doc_snapshot": None,
    "has_more_content": True,
    "is_loading_content": True, # Start loading content on first run of "My Content"
    "deleting_item_id": None,
    "editing_item_id": None,

}
for key, value in default_session_state.items():
    if key not in st.session_state:
        st.session_state[key] = value

# Ensure user ID is set
get_user_id()

# Sidebar Navigation
with st.sidebar:
    st.title("Conteúdo IA")
    
    # Simplified user display
    st.markdown(f"👤 **{get_user_display_name()}**")
    st.caption(f"ID: {st.session_state.user_id[:10]}...") # Show first 10 chars of ID
    st.divider()

    # Using streamlit_option_menu for a nicer look
    # Icons from: https://icons.getbootstrap.com/ (use names) or emojis
    app_mode = option_menu(
        menu_title=None, # "Menu Principal",
        options=["Dashboard", "Ferramentas", "Meus Conteúdos"],
        icons=["speedometer2", "tools", "archive-fill"], # Bootstrap icons
        menu_icon="cast", default_index=0,
        # orientation="horizontal", # If you want horizontal menu
        styles={
            "container": {"padding": "5!important", "background-color": "#fafafa"},
            # "icon": {"color": "orange", "font-size": "25px"}, 
            # "nav-link": {"font-size": "16px", "text-align": "left", "margin":"0px", "--hover-color": "#eee"},
            # "nav-link-selected": {"background-color": "#02ab21"},
        }
    )

    if app_mode == "Dashboard":
        st.session_state.current_page = "dashboard"
    elif app_mode == "Meus Conteúdos":
        st.session_state.current_page = "my-content"
    elif app_mode == "Ferramentas":
        # Sub-menu for tools
        selected_tool_name = option_menu(
            menu_title="Escolha uma Ferramenta",
            options=[config['name'] for config in tool_configs.values()],
            icons=[config['icon'] for config in tool_configs.values()], # Using emojis as icons here
            menu_icon="chevron-down", # Optional: an icon for the submenu itself
            default_index=0
        )
        # Find the tool_key based on the selected_tool_name
        for tool_key_iter, config_iter in tool_configs.items():
            if config_iter['name'] == selected_tool_name:
                st.session_state.current_page = f"tool/{tool_key_iter}"
                break
    
    # st.info("Este é um app de demonstração adaptado de um projeto React.")


# Page Routing
page_parts = st.session_state.current_page.split('/')
page_type = page_parts[0]
page_arg = page_parts[1] if len(page_parts) > 1 else None

if page_type == "dashboard":
    render_dashboard_page()
elif page_type == "tool" and page_arg:
    render_tool_page(page_arg)
elif page_type == "my-content":
    render_my_content_page()
else:
    render_dashboard_page() # Default to dashboard

