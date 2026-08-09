import datetime
import json
import time
import pypdf
import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# ------------------------------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="GASP | Analista Jurídico v2.1",
    page_icon="⚖️",
    layout="wide",
)

st.title("⚖️ Analista Jurídico (v2.1) — Filtro de Impedimentos")
st.caption(
    "Arquitetura Determinística Anti-Alucinação com Leitura Nativa de PDF (SEEU & BNMP 3.0)"
)

# ------------------------------------------------------------------------------
# GERENCIAMENTO SEGURO DA API KEY (SECRETS OU SIDEBAR)
# ------------------------------------------------------------------------------
api_key = None

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]

with st.sidebar:
    st.header("Status do Sistema")
    if api_key:
        st.success("🔑 API Key do Gemini carregada dos Secrets!")
    else:
        st.warning("⚠️ API Key não encontrada nos Secrets.")
        api_key = st.text_input(
            "Informe a Gemini API Key manualmente:", type="password"
        )

    st.markdown("---")
    st.info(
        "O texto dos PDFs é extraído localmente e enviado para o Gemini apenas para "
        "estruturação de dados em JSON. A análise do Cenário A/B roda em Python."
    )


# ------------------------------------------------------------------------------
# SCHEMAS DE EXTRAÇÃO ESTRUTURADA (PYDANTIC)
# ------------------------------------------------------------------------------
class PecaBNMP(BaseModel):
    nup: str = Field(
        description="NUP do processo associado à peça mantendo a pontuação CNJ NNNNNNN-DD.AAAA.J.TR.OOOO"
    )
    nome_peca: str = Field(description="Nome exato da peça no extrato BNMP")
    status: str = Field(
        description="Status atual da peça (ex: Cumprido, Pendente de Cumprimento, Baixado, Revogado)"
    )
    data_emissao: str = Field(
        description="Data de emissão da peça no formato YYYY-MM-DD"
    )


class ExtracaoProcessual(BaseModel):
    nup_execucao_principal: str = Field(
        description="Número Único da Execução Penal contido no relatório SEEU"
    )
    nups_conhecimento: list[str] = Field(
        description="Lista de NUPs de todos os processos de conhecimento/origem listados no relatório de execução"
    )
    pecas_bnmp: list[PecaBNMP] = Field(
        description="Lista de todas as peças identificadas no extrato do BNMP 3.0"
    )


# ------------------------------------------------------------------------------
# EXTRAÇÃO DE TEXTO DOS PDFS (LOCAL E RÁPIDA VIA PYPDF)
# ------------------------------------------------------------------------------
def extrair_texto_pdf(file_bytes):
    reader = pypdf.PdfReader(file_bytes)
    texto = ""
    for page in reader.pages:
        t = page.extract_text()
        if t:
            texto += t + "\n"
    return texto


# ------------------------------------------------------------------------------
# EXTRAÇÃO VIA GEMINI API (MODELO OFICIAL COM FALLBACK E ESTRUTURAÇÃO ENFORCADA)
# ------------------------------------------------------------------------------
def extrair_dados_com_gemini(texto_seeu, texto_bnmp, api_key_val):
    client = genai.Client(api_key=api_key_val)

    prompt = f"""
    Sua única função é ler os textos extraídos dos documentos (Relatório do SEEU e Extrato do BNMP 3.0) 
    e extrair os dados processuais solicitados, preenchendo o esquema JSON estrito fornecido.
    
    Instruções de Extração:
    1. Identifique o NUP principal da execução e todos os NUPs dos processos de conhecimento/origem do SEEU.
    2. Identifique todas as peças do BNMP com seus respectivos NUPs, Nomes de Peça, Status e Datas de Emissão.
    3. Não deduza, não infira e não crie dados que não estejam visíveis no texto.
    
    TEXTO RELATÓRIO SEEU:
    ---
    {texto_seeu}
    ---
    
    TEXTO EXTRATO BNMP 3.0:
    ---
    {texto_bnmp}
    ---
    """

    configuracao = types.GenerateContentConfig(
        temperature=0.0,
        response_mime_type="application/json",
        response_schema=ExtracaoProcessual,
    )

    # Nomes oficiais suportados pelo SDK novo google-genai
    modelos = ["gemini-2.0-flash", "gemini-2.5-flash"]

    for modelo in modelos:
        try:
            response = client.models.generate_content(
                model=modelo,
                contents=prompt,
                config=configuracao,
            )
            return json.loads(response.text)
        except Exception as e:
            erro_str = str(e)
            if "429" in erro_str or "404" in erro_str or "RESOURCE_EXHAUSTED" in erro_str:
                if modelo != modelos[-1]:
                    time.sleep(1)
                    continue
                else:
                    raise Exception(
                        f"Erro na comunicação com a API do Gemini: {erro_str}"
                    )
            else:
                raise e


# ------------------------------------------------------------------------------
# MOTOR LÓGICO DETERMINÍSTICO EM PYTHON (INSTRUÇÕES v2.1)
# ------------------------------------------------------------------------------
def converter_data(data_str: str):
    try:
        return datetime.datetime.strptime(data_str.strip(), "%Y-%m-%d").date()
    except Exception:
        return datetime.date.min


def aplicar_regras_v2_1(dados):
    # ETAPA 2: MAPEAMENTO DA EXECUÇÃO (Lista de Exclusão Primária)
    lista_exclusao = [dados.get("nup_execucao_principal", "").strip()]
    lista_exclusao.extend([n.strip() for n in dados.get("nups_conhecimento", [])])
    lista_exclusao = [n for n in lista_exclusao if n]

    pecas = dados.get("pecas_bnmp", [])
    mandados_analise = []
    restricoes_reais = []

    # ETAPA 1: FILTRAGEM (Mandado de Prisão Cumprido ou Pendente)
    for p in pecas:
        nome = p.get("nome_peca", "").lower()
        status = p.get("status", "").lower()
        if "mandado de prisão" in nome or "mandado de prisao" in nome:
            if status in ["cumprido", "pendente de cumprimento", "pendente"]:
                mandados_analise.append(p)

    # ETAPAS 2 E 3: ANÁLISE LÓGICA
    for mandado in mandados_analise:
        nup_mandado = mandado.get("nup", "").strip()
        data_mandado = converter_data(mandado.get("data_emissao", ""))

        # REGRA DE OURO (FILTRO DE IDENTIDADE / BLOQUEIO DE FALSO POSITIVO)
        if nup_mandado in lista_exclusao:
            continue

        # ETAPA 3: ANÁLISE DE PROCESSO ESTRANHO (VERIFICAÇÃO DE CONTRA-PEÇA)
        contra_pecas = [
            p
            for p in pecas
            if p.get("nup", "").strip() == nup_mandado
            and any(
                cp in p.get("nome_peca", "").lower()
                for cp in ["alvará", "alvara", "contramandado"]
            )
        ]

        status_final = "PROVÁVEL RESTRIÇÃO"
        motivo = "Mandado de Prisão identificado em processo que **NÃO** consta no Relatório de Execução e não possui contra-peça posterior."

        if contra_pecas:
            contra_pecas.sort(
                key=lambda x: converter_data(x.get("data_emissao", "")),
                reverse=True,
            )
            data_contra = converter_data(contra_pecas[0].get("data_emissao", ""))

            if data_contra > data_mandado:
                continue
            elif data_contra == data_mandado:
                status_final = "ANÁLISE MANUAL (BNMP 3.0)"
                motivo = "Mandado e Alvará/Contramandado possuem a **EXATA MESMA DATA**."

        restricoes_reais.append(
            {
                "nup": nup_mandado,
                "status": status_final,
                "motivo": motivo,
                "data_mandado": mandado.get("data_emissao"),
                "status_mandado": mandado.get("status"),
            }
        )

    # FORMATO DO OUTPUT OBRIGATÓRIO (CENÁRIO A vs CENÁRIO B)
    if not restricoes_reais:
        return (
            "Cenário A",
            "Análise Detalhada: **Não foram encontradas restrições impeditivas.** "
            "Todos os mandados analisados referem-se aos processos já constantes na execução atual "
            "ou possuem baixa processual clara. (Falsos positivos de Número Único foram filtrados).",
        )
    else:
        r = restricoes_reais[0]
        texto = (
            "Análise Detalhada: **Foi encontrada uma restrição externa que impede a progressão/soltura.**\n\n"
            "---\n"
            f"### Detalhamento do Processo Nº {r['nup']}\n"
            f"**Status da Análise:** [{r['status']}]\n\n"
            f"**Motivo:** {r['motivo']}\n\n"
            "**Análise Cronológica:**\n"
            f"* {r['data_mandado']} - Mandado de Prisão - {r['status_mandado']}\n\n"
            "**Ação Necessária:** Consultar processo de origem para verificar se a ordem de prisão "
            "ainda subsiste ou se houve omissão de baixa no BNMP."
        )
        return "Cenário B", texto


# ------------------------------------------------------------------------------
# INTERFACE GRÁFICA (UPLOAD DE ARQUIVOS PDF)
# ------------------------------------------------------------------------------
col1, col2 = st.columns(2)

with col1:
    st.subheader("📄 Relatório de Execução (SEEU)")
    file_seeu = st.file_uploader(
        "Faça o upload do PDF do Relatório de Situação Processual:",
        type=["pdf"],
        key="seeu_pdf",
    )

with col2:
    st.subheader("🔍 Extrato BNMP 3.0")
    file_bnmp = st.file_uploader(
        "Faça o upload do PDF do Extrato de Pesquisa do BNMP 3.0:",
        type=["pdf"],
        key="bnmp_pdf",
    )

if st.button("Executar Análise Lógica v2.1", type="primary", use_container_width=True):
    if not api_key:
        st.error(
            "Chave da API do Gemini não configurada. Configure no Secrets do Streamlit Cloud ou informe na barra lateral."
        )
    elif not file_seeu or not file_bnmp:
        st.warning(
            "Envie ambos os arquivos PDF (SEEU e BNMP) para iniciar a análise."
        )
    else:
        with st.spinner("Processando PDFs e realizando análise lógica v2.1..."):
            try:
                # 1. Extração local de texto via Python
                texto_seeu = extrair_texto_pdf(file_seeu)
                texto_bnmp = extrair_texto_pdf(file_bnmp)

                # 2. IA extrai os dados estruturados em JSON
                dados_json = extrair_dados_com_gemini(
                    texto_seeu, texto_bnmp, api_key
                )

                # Auditoria visual
                with st.expander("🛠️ Ver Dados Estruturados (Auditoria de Extração)"):
                    st.json(dados_json)

                # 3. Validação lógica determinística em Python
                cenario, texto_final = aplicar_regras_v2_1(dados_json)

                st.markdown("---")
                if cenario == "Cenário A":
                    st.success(texto_final)
                else:
                    st.error(texto_final)

            except Exception as e:
                st.error(f"Erro ao processar os arquivos PDF: {str(e)}")
