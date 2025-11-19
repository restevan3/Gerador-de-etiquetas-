import streamlit as st
import socket
import os
import psycopg2
import time
import pandas as pd

# -----------------------------------------------------------------------------
# 1. CONFIGURAÇÃO E CONEXÃO COM BANCO DE DADOS
# -----------------------------------------------------------------------------

def get_db_connection():
    max_retries = 5
    for i in range(max_retries):
        try:
            conn = psycopg2.connect(
                host=os.environ.get('DB_HOST', 'db'),
                user=os.environ.get('DB_USER', 'postgres'),
                password=os.environ.get('DB_PASSWORD', 'minhasenha'),
                database=os.environ.get('DB_NAME', 'etiquetas_db')
            )
            return conn
        except psycopg2.OperationalError:
            if i < max_retries - 1:
                time.sleep(2)
                continue
            else:
                st.error("🚨 Não foi possível conectar ao banco de dados.")
                raise

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS departamentos (
            id SERIAL PRIMARY KEY,
            nome_exibicao VARCHAR(100) UNIQUE NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lojas (
            id SERIAL PRIMARY KEY,
            nome VARCHAR(100) UNIQUE NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS balancas (
            id SERIAL PRIMARY KEY,
            numero INT NOT NULL,
            loja_id INT REFERENCES lojas(id) ON DELETE CASCADE,
            depto_nome VARCHAR(100) NOT NULL,
            detalhes_qr TEXT,
            UNIQUE(numero, loja_id)
        );
    """)
    
    cur.execute("SELECT COUNT(*) FROM departamentos;")
    if cur.fetchone()[0] == 0:
        deptos = ["Açougue", "Padaria", "PAS", "Hortifruti", "Rotisseria", "Selfcheckout", "Drive Thru", "Peixaria"]
        for d in deptos:
            cur.execute("INSERT INTO departamentos (nome_exibicao) VALUES (%s) ON CONFLICT DO NOTHING", (d,))
        conn.commit()
    
    conn.commit()
    cur.close()
    conn.close()

# --- FUNÇÕES DE CRUD ---

def criar_loja(nome_loja):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO lojas (nome) VALUES (%s)", (nome_loja,))
        conn.commit()
        return True, "Loja criada com sucesso!"
    except psycopg2.IntegrityError:
        conn.rollback()
        return False, "Essa loja já existe."
    finally:
        cur.close()
        conn.close()

def salvar_balanca(loja_nome, numero, depto, detalhes):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM lojas WHERE nome = %s", (loja_nome,))
    res = cur.fetchone()
    if not res:
        return False, "Loja não encontrada."
    loja_id = res[0]

    try:
        cur.execute("""
            INSERT INTO balancas (numero, loja_id, depto_nome, detalhes_qr)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (numero, loja_id) 
            DO UPDATE SET depto_nome = EXCLUDED.depto_nome, detalhes_qr = EXCLUDED.detalhes_qr;
        """, (numero, loja_id, depto, detalhes))
        conn.commit()
        return True, "Balança salva!"
    except Exception as e:
        conn.rollback()
        return False, f"Erro ao salvar: {e}"
    finally:
        cur.close()
        conn.close()

def excluir_balanca(loja_nome, numero):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM lojas WHERE nome = %s", (loja_nome,))
        res = cur.fetchone()
        if not res: return False, "Loja não encontrada"
        loja_id = res[0]
        
        cur.execute("DELETE FROM balancas WHERE loja_id = %s AND numero = %s", (loja_id, numero))
        conn.commit()
        return True, "Balança excluída!"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        cur.close()
        conn.close()

def limpar_loja_inteira(loja_nome):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM lojas WHERE nome = %s", (loja_nome,))
        loja_id = cur.fetchone()[0]
        cur.execute("DELETE FROM balancas WHERE loja_id = %s", (loja_id,))
        conn.commit()
        return True, "Loja limpa com sucesso!"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        cur.close()
        conn.close()

def listar_lojas():
    conn = get_db_connection()
    df = pd.read_sql("SELECT nome FROM lojas ORDER BY nome", conn)
    conn.close()
    return df['nome'].tolist()

def listar_departamentos():
    conn = get_db_connection()
    df = pd.read_sql("SELECT nome_exibicao FROM departamentos ORDER BY nome_exibicao", conn)
    conn.close()
    return df['nome_exibicao'].tolist()

def listar_balancas_da_loja(nome_loja):
    conn = get_db_connection()
    query = """
        SELECT b.numero, b.depto_nome, b.detalhes_qr 
        FROM balancas b
        JOIN lojas l ON b.loja_id = l.id
        WHERE l.nome = %s
        ORDER BY b.numero ASC
    """
    df = pd.read_sql(query, conn, params=(nome_loja,))
    conn.close()
    return df

# -----------------------------------------------------------------------------
# 2. FUNÇÕES DE IMPRESSÃO ZPL
# -----------------------------------------------------------------------------

def gerar_zpl_etiqueta_decorada(numero_balanca, nome_departamento, quantidade, dados_qr):
    if not dados_qr:
        dados_qr = f"Balanca:{numero_balanca}|Depto:{nome_departamento}"

    qr_content_tratado = dados_qr.replace("\n", "_0D_0A")

    zpl_code = f"""
^XA
^CI28
^PW320
^LL320
^FO10,10^GB300,300,3^FS

^FX --- ZONA DE TEXTO (TOPO) ---
^FO0,30^FB320,1,0,C,0^A0N,25,25^FDDepartamento:^FS
^FO0,60^FB320,1,0,C,0^A0N,35,35^FD{nome_departamento}^FS

^FX --- ZONA DA BALANÇA ---
^FO0,100^FB320,1,0,C,0^A0N,25,25^FDBalanca:^FS
^FO0,125^FB320,1,0,C,0^A0N,60,60^FD{numero_balanca}^FS

^FX --- ZONA DO QR CODE (BASE) ---
^FO110,180^BQ,2,2,M^FH^FDQA,{qr_content_tratado}^FS

^PQ{quantidade}
^XZ
"""
    return zpl_code.strip()

def enviar_para_impressora(ip_impressora, zpl_data):
    porta_impressora = 9100
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect((ip_impressora, porta_impressora))
            s.sendall(zpl_data.encode('utf-8'))
            return True, "OK"
    except Exception as e:
        return False, str(e)

# -----------------------------------------------------------------------------
# 3. INTERFACE DO STREAMLIT
# -----------------------------------------------------------------------------

st.set_page_config(page_title="Sistema de Etiquetas", page_icon="🏭", layout="wide")

try:
    init_db()
except:
    st.stop()

if "editor_key" not in st.session_state:
    st.session_state.editor_key = 0

st.title("🏭 Gerenciador de Etiquetas de Balança")

tab_imprimir, tab_cadastro, tab_config = st.tabs(["🖨️ Selecionar e Imprimir", "📝 Gerenciar Balanças", "⚙️ Gerenciar Lojas"])

# --- ABA 1: IMPRIMIR ---
with tab_imprimir:
    st.header("Painel de Impressão")
    
    lojas_disponiveis = listar_lojas()
    
    if not lojas_disponiveis:
        st.warning("Nenhuma loja cadastrada.")
    else:
        col_sel_1, col_sel_2 = st.columns(2)
        with col_sel_1:
            loja_selecionada = st.selectbox("Selecione a Loja:", lojas_disponiveis)
        with col_sel_2:
            ip_impressora = st.text_input("IP da Impressora", "192.168.1.100")
            qtd_copias = st.number_input("Cópias por etiqueta", min_value=1, value=1)

        if "ultima_loja" not in st.session_state or st.session_state.ultima_loja != loja_selecionada:
            st.session_state.ultima_loja = loja_selecionada
            df_raw = listar_balancas_da_loja(loja_selecionada)
            if not df_raw.empty:
                df_raw.insert(0, "Selecionar", False)
            st.session_state.df_balancas = df_raw
            st.session_state.editor_key += 1

        if st.session_state.df_balancas.empty:
            st.info(f"A loja '{loja_selecionada}' não tem balanças cadastradas.")
        else:
            st.write("Selecione as balanças:")
            col_btn1, col_btn2, col_vazia = st.columns([1, 1, 6])
            if col_btn1.button("✅ Marcar Todas"):
                st.session_state.df_balancas["Selecionar"] = True
                st.session_state.editor_key += 1 
                st.rerun()
            if col_btn2.button("⬜ Desmarcar"):
                st.session_state.df_balancas["Selecionar"] = False
                st.session_state.editor_key += 1
                st.rerun()

            df_editado = st.data_editor(
                st.session_state.df_balancas,
                column_config={
                    "Selecionar": st.column_config.CheckboxColumn("Imprimir?", width="small", default=False),
                    "numero": st.column_config.NumberColumn("Nº Balança", format="%d"),
                    "depto_nome": "Departamento",
                    "detalhes_qr": "QR Code (Dados)"
                },
                disabled=["numero", "depto_nome", "detalhes_qr"],
                hide_index=True,
                use_container_width=True,
                key=f"editor_{st.session_state.editor_key}" 
            )
            
            st.session_state.df_balancas = df_editado

            balancas_para_imprimir = df_editado[df_editado["Selecionar"] == True]
            qtd_selecionada = len(balancas_para_imprimir)
            
            st.write(f"**Itens selecionados:** {qtd_selecionada}")

            if st.button(f"🖨️ IMPRIMIR {qtd_selecionada} ETIQUETAS", type="primary", disabled=(qtd_selecionada == 0)):
                sucesso_count = 0
                erro_count = 0
                bar = st.progress(0)
                status_text = st.empty()
                total = len(balancas_para_imprimir)
                
                for index, row in balancas_para_imprimir.iterrows():
                    status_text.text(f"Enviando Balança {row['numero']}...")
                    zpl = gerar_zpl_etiqueta_decorada(row['numero'], row['depto_nome'], qtd_copias, row['detalhes_qr'])
                    ok, msg = enviar_para_impressora(ip_impressora, zpl)
                    
                    if ok: sucesso_count += 1
                    else: 
                        erro_count += 1
                        st.error(f"Erro balança {row['numero']}: {msg}")
                    
                    current_pos = list(balancas_para_imprimir.index).index(index) + 1
                    bar.progress(current_pos / total)
                
                bar.empty()
                status_text.empty()
                
                if erro_count == 0:
                    st.toast(f"Enviadas com sucesso!", icon="✅")
                    st.success("Impressão finalizada!")
                else:
                    st.warning(f"Finalizado com erros: {erro_count}")

# --- ABA 2: GERENCIAR BALANÇAS ---
with tab_cadastro:
    st.header("📝 Adicionar ou Remover Balanças")
    lojas = listar_lojas()
    deptos = listar_departamentos()
    
    if not lojas:
        st.error("Cadastre uma loja primeiro.")
    else:
        # CADASTRO
        with st.expander("➕ Adicionar Nova Balança", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                c_loja = st.selectbox("Loja:", lojas, key="cad_loja")
                c_numero = st.number_input("Número:", min_value=1, step=1, key="cad_num")
                c_depto = st.selectbox("Departamento:", deptos, key="cad_dep")
            with col2:
                c_detalhes = st.text_area("QR Code:", height=100, value="Modelo:\nNS:\nIP:", key="cad_qr")
                
            if st.button("💾 Salvar Balança"):
                ok, msg = salvar_balanca(c_loja, c_numero, c_depto, c_detalhes)
                if ok:
                    st.success(f"Balança {c_numero} salva!")
                    time.sleep(0.5)
                    if "ultima_loja" in st.session_state: del st.session_state["ultima_loja"]
                    st.rerun()
                else:
                    st.error(msg)

        st.divider()
        
        # EXCLUSÃO
        st.subheader(f"⚖️ Balanças Existentes em: {c_loja}")
        df_existentes = listar_balancas_da_loja(c_loja)
        
        if df_existentes.empty:
            st.info("Nenhuma balança cadastrada nesta loja.")
        else:
            st.dataframe(df_existentes, use_container_width=True)
            
            col_del1, col_del2 = st.columns(2)
            
            # Excluir Individual
            with col_del1:
                st.write("**Excluir Individualmente**")
                num_to_del = st.selectbox("Qual balança apagar?", df_existentes['numero'].tolist())
                if st.button(f"❌ Apagar Balança {num_to_del}"):
                    ok, msg = excluir_balanca(c_loja, num_to_del)
                    if ok:
                        st.toast(f"Balança {num_to_del} removida.")
                        time.sleep(0.5)
                        if "ultima_loja" in st.session_state: del st.session_state["ultima_loja"]
                        st.rerun()
            
            # Excluir TUDO (Zona de Perigo com Confirmação)
            with col_del2:
                st.write("**Zona de Perigo**")
                
                # Estado para controlar se o aviso aparece ou não
                if "confirmar_limpeza" not in st.session_state:
                    st.session_state.confirmar_limpeza = False

                if not st.session_state.confirmar_limpeza:
                    # Botão normal
                    if st.button(f"🔥 LIMPAR TODAS AS BALANÇAS", type="primary"):
                        st.session_state.confirmar_limpeza = True
                        st.rerun()
                else:
                    # Modo Confirmação
                    st.error(f"⚠️ TEM CERTEZA? Você vai apagar TODAS as balanças da {c_loja}!")
                    col_conf1, col_conf2 = st.columns(2)
                    
                    if col_conf1.button("✅ SIM, APAGAR TUDO"):
                        ok, msg = limpar_loja_inteira(c_loja)
                        st.session_state.confirmar_limpeza = False # Reseta
                        if ok:
                            st.toast("Loja limpa com sucesso!")
                            if "ultima_loja" in st.session_state: del st.session_state["ultima_loja"]
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)
                            
                    if col_conf2.button("❌ CANCELAR"):
                        st.session_state.confirmar_limpeza = False
                        st.rerun()

# --- ABA 3: CONFIGURAÇÕES ---
with tab_config:
    st.header("Gerenciar Lojas")
    nova_loja = st.text_input("Nome da Nova Loja")
    if st.button("Criar Loja"):
        if nova_loja:
            ok, msg = criar_loja(nova_loja)
            if ok:
                st.success(msg)
                time.sleep(0.5)
                st.rerun()
            else:
                st.error(msg)
    st.write("Lojas Atuais:")
    st.write(listar_lojas())