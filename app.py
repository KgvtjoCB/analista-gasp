import streamlit as st
import google.generativeai as genai

# ------------------------------------------------------------------------------
# INSTRUÇÕES DO SISTEMA (VERSÃO 2.1)
# ------------------------------------------------------------------------------
INSTRUCOES_SISTEMA = """
# INSTRUÇÕES DO ANALISTA JURÍDICO (VERSÃO 2.1 - BLOQUEIO DE FALSO POSITIVO)

**Perfil:** Analista de documentos jurídicos especializado em identificar restrições impeditivas (impedimentos de soltura ou progressão).
**Foco Crítico:** Diferenciar o que é **processo em execução** (não impede) do que é **processo externo/novo** (impede).

---

### ETAPA 1: PROCESSAMENTO E FILTRAGEM (EXTRATO_BNMP)
1. **Filtro de Nome:** Analise **exclusivamente** registros cujo `Nome_Peca` seja "Mandado de Prisão".
2. **Filtro de Status:** Ignore mandados com Status: `Baixado`, `Revogado`, `Cancelado` ou `Excluído`.
3. **Retenção:** Mantenha apenas mandados com Status: `Cumprido` ou `Pendente de Cumprimento`.
4. **Normalização:** Converta todos os NUPs para o formato padrão CNJ (`NNNNNNN-DD.AAAA.JTR.OOOO`).

### ETAPA 2: MAPEAMENTO DA EXECUÇÃO (BLOQUEIO DE FALSO POSITIVO)
1. **Extração de Dados:** Identifique o **Número Único da Execução** e todos os NUPs de processos de conhecimento listados no `RELATORIO_SITUACAO_PROCESSUAL_EXECUTORIA`.
2. **REGRA DE OURO (FILTRO DE IDENTIDADE):** Estes números compõem a "Lista de Exclusão Primária".
3. **BLOQUEIO DE FALSO POSITIVO:** Se o NUP de um Mandado de Prisão (BNMP) for **IGUAL** a qualquer NUP presente no Relatório de Execução, ele deve ser sumariamente desconsiderado como restrição. 
   * *Justificativa:* O mandado pertence à própria prisão que está sendo executada.
   * *Ação:* Classifique como **"PROCESSO EM EXECUÇÃO - SEM RESTRIÇÃO"**.

### ETAPA 3: ANÁLISE LÓGICA E VEREDITO
Para os mandados que **NÃO** pertencem à execução (NUPs estranhos ao relatório), aplique:

**1. Verificação de Contra-peça (Cronologia):**
* Busque no extrato por "Alvará de Soltura" ou "Contramandado" no mesmo NUP:
    * **DATA POSTERIOR:** Contra-peça mais recente que o mandado -> **SEM RESTRIÇÃO**.
    * **MESMA DATA:** Se a contra-peça tiver a **EXATA MESMA DATA** que o mandado -> **STATUS: ANÁLISE MANUAL (BNMP 3.0)**.
    * **SEM CONTRA-PEÇA:** Mandado ativo/cumprido sem baixa posterior -> **PROVÁVEL RESTRIÇÃO**.

---

### FORMATO DO OUTPUT (OBRIGATÓRIO)

**Cenário A: Nenhuma Restrição (Tudo sob controle da Execução)**
> "Análise Detalhada: **Não foram encontradas restrições impeditivas.** Todos os mandados analisados referem-se aos processos já constantes na execução atual ou possuem baixa processual clara. (Falsos positivos de Número Único foram filtrados)."

**Cenário B: Identificação de Pendências Reais (Processos Externos)**
> "Análise Detalhada: **Foi encontrada uma restrição externa que impede a progressão/soltura.**
>
> ---
> ### Detalhamento do Processo Nº [NUP Estranho à Execução]
> **Status da Análise:** [PROVÁVEL RESTRIÇÃO]
>
> **Motivo:** Mandado de Prisão identificado em processo que **NÃO** consta no Relatório de Execução e não possui contra-peça posterior.
>
> **Análise Cronológica:**
> * [Data] - [Mandado de Prisão] - [Status]
>
> **Ação Necessária:** Consultar processo de origem para verificar se a ordem de prisão ainda subsiste ou se houve omissão de baixa no BNMP."

---

### DIRETRIZES DE PRECISÃO
* **Rigor Sistêmico:** Se o NUP do mandado estiver no Relatório de Execução, **IGNORE-O**. O foco é o "processo de fora".
* **Conflito de Datas:** O empate de datas exige cautela máxima (BNMP 3.0), pois pode haver variação de horários não listados na peça.
"""

# ------------------------------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="GASP | Analista Jurídico v2.1",
    page_icon="⚖️",
    layout="wide",
)

st.title("⚖️ Analista Jurídico (v2.1) — Filtro de Impedimentos")
st.caption("Leitura Multimodal e Análise Semântica (SDK Estável)")

# ------------------------------------------------------------------------------
# GERENCIAMENTO DA API KEY
# ------------------------------------------------------------------------------
api_key = None

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]

with st.sidebar:
    st.header("Status do Sistema")
    if api_key:
        st.success("🔑 API Key carregada com sucesso!")
    else:
        st.warning("⚠️ API Key não encontrada.")
        api_key = st.text_input("Informe a Gemini API Key:", type="password")
    
    st.markdown("---")
    st.info(
        "Utilizando o SDK estável (`google-generativeai`) para leitura visual nativa. "
        "Imune a quebras de tabela e erros de roteamento de API."
    )

# ------------------------------------------------------------------------------
# MOTOR DE ANÁLISE MULTIMODAL (SDK ESTÁVEL)
# ------------------------------------------------------------------------------
def analisar_documentos_gemini(pdf_seeu_bytes, pdf_bnmp_bytes, api_key_val):
    # Configura a chave na biblioteca clássica
    genai.configure(api_key=api_key_val)
    
    # Instancia o modelo com a instrução do sistema travada
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash-latest",
        system_instruction=INSTRUCOES_SISTEMA,
        generation_config={"temperature": 0.0}
    )
    
    # Prepara os PDFs como blobs de dados nativos
    doc_seeu = {
        "mime_type": "application/pdf",
        "data": pdf_seeu_bytes
    }
    doc_bnmp = {
        "mime_type": "application/pdf",
        "data": pdf_bnmp_bytes
    }
    
    prompt_usuario = (
        "Leia os dois documentos PDF anexados (SEEU e BNMP). Aplique estritamente as diretrizes "
        "passadas nas Instruções de Sistema e me devolva EXATAMENTE o texto de output formatado "
        "como Cenário A ou Cenário B. Não adicione nenhuma saudação, conclusão ou texto extra."
    )
    
    try:
        response = model.generate_content([doc_seeu, doc_bnmp, prompt_usuario])
        return response.text
    except Exception as e:
        raise Exception(f"Erro de comunicação com a API: {str(e)}")


# ------------------------------------------------------------------------------
# INTERFACE GRÁFICA
# ------------------------------------------------------------------------------
col1, col2 = st.columns(2)

with col1:
    st.subheader("📄 Relatório de Execução (SEEU)")
    file_seeu = st.file_uploader("Upload do PDF do SEEU:", type=["pdf"], key="seeu")

with col2:
    st.subheader("🔍 Extrato BNMP 3.0")
    file_bnmp = st.file_uploader("Upload do PDF do BNMP:", type=["pdf"], key="bnmp")

if st.button("Executar Análise V2.1", type="primary", use_container_width=True):
    if not api_key:
        st.error("Chave da API não configurada.")
    elif not file_seeu or not file_bnmp:
        st.warning("Envie os dois arquivos PDF para iniciar a análise.")
    else:
        with st.spinner("Lendo PDFs e cruzando dados processuais..."):
            try:
                # Executa a IA
                resultado = analisar_documentos_gemini(
                    file_seeu.read(), 
                    file_bnmp.read(), 
                    api_key
                )
                
                st.markdown("---")
                
                # Exibição visual condicionada ao resultado
                if "Cenário A" in resultado or "Não foram encontradas restrições" in resultado:
                    st.success(resultado.replace("Cenário A:", "").replace("Cenário A", "").strip())
                else:
                    st.error(resultado.replace("Cenário B:", "").replace("Cenário B", "").strip())
                    
            except Exception as e:
                st.error(f"Erro durante a análise: {str(e)}")
