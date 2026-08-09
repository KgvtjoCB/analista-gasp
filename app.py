import datetime
import json
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
st.caption("Arquitetura Determinística Anti-Alucinação com Upload de PDF (SEEU & BNMP 3.0)")

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
        api_key = st.text_input("Informe a Gemini API Key manualmente:", type="password")
    
    st.markdown("---")
    st.info(
        "A IA realiza unicamente a leitura OCR do PDF e extração dos dados estruturados em JSON. "
        "Toda a lógica de bloqueio de falsos positivos roda no backend Python."
    )

# ------------------------------------------------------------------------------
# SCHEMAS DE EXTRAÇÃO ESTRUTURADA
# ------------------------------------------------------------------------------
class PecaBNMP(BaseModel):
    nup: str = Field(
        description="NUP do processo associado à peça no formato CNJ NNNNNNN-DD.AAAA.J.TR.OOOO"
    )
    nome_peca: str = Field(description="Nome exato da peça")
    status: str = Field(description="Status atual da peça (ex: Cumprido, Pendente de Cumprimento)")
    data_emissao: str = Field(description="Data de emissão no formato YYYY-MM-DD")


class ExtracaoProcessual(BaseModel):
    nup_execucao_principal: str = Field(description="Número Único da Execução Penal")
    nups_conhecimento: list[str] = Field(
        description="Lista de NUPs dos processos de conhecimento/origem listados no relatório de execução"
    )
    pecas_bnmp: list[PecaBNMP] = Field(description="Lista de todas as peças encontradas no BNMP")


# ------------------------------------------------------------------------------
# EXTRAÇÃO VIA GEMINI API COM LEITURA DIRETA DE PDF (TEMPERATURE = 0.0)
# ------------------------------------------------------------------------------
def extrair_dados_pdf(pdf_seeu_bytes, pdf_bnmp_bytes, api_key_val):
    client = genai.Client(api_key=api_key_val)

    prompt = """
    Sua única função é ler os dois documentos PDF anexados (Relatório do SEEU e Extrato do BNMP 3.0) 
    e extrair os dados processuais informados preenchendo o esquema JSON estrito fornecido.
    
    Instruções de Extração:
    1. Identifique o NUP principal da execução e todos os NUPs de conhecimento do SEEU.
    2. Identifique todas as peças do BNMP com seus respectivos NUPs, Nomes de Peça, Status e Datas de Emissão.
    3. Não deduza, não infira e não crie dados que não estejam visíveis nos PDFs.
    """

    # Envia os arquivos PDF diretamente na requisição usando types.Part.from_bytes
    part_seeu = types.Part.from_bytes(data=pdf_seeu_bytes, mime_type="application/pdf")
    part_bnmp = types.Part.from_bytes(data=pdf_bnmp_bytes, mime_type="application/pdf")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[part_seeu, part_bnmp, prompt],
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=ExtracaoProcessual,
        ),
    )
    return json.loads(response.text)


# ------------------------------------------------------------------------------
# MOTOR LÓGICO DETERMINÍSTICO (INSTRUÇÕES v2.1)
# ------------------------------------------------------------------------------
def converter_data(data_str: str):
    try:
        return datetime.datetime.strptime(data_str.strip(), "%Y-%m-%d").date()
    except Exception:
        return datetime.date.min


def aplicar_regras_v2_1(dados):
    lista_exclusao = [dados.get("nup_execucao_principal", "").strip()]
    lista_exclusao.extend([n.strip() for n in dados.get("nups_conhecimento", [])])
    lista_exclusao = [n for n in lista_exclusao if n]

    pecas = dados.get("pecas_bnmp", [])
    mandados_analise = []
    restricoes_reais = []

    for p in pecas:
        nome = p.get("nome_peca", "").lower()
        status = p.get("status", "").lower()
        if "mandado de prisão" in nome or "mandado de prisao" in nome:
            if status in ["cumprido", "pendente de cumprimento", "pendente"]:
                mandados_analise.append(p)

    for mandado in mandados_analise:
        nup_mandado = mandado.get("nup", "").strip()
        data_mandado = converter_data(mandado.get("data_emissao", ""))

        if nup_mandado in lista_exclusao:
            continue

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
                key=lambda x: converter_data(x.get("data_emissao", "")), reverse=True
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
        st.error("Chave da API do Gemini não configurada.")
    elif not file_seeu or not file_bnmp:
        st.warning("Envie os dois arquivos PDF (SEEU e BNMP) para iniciar a análise.")
    else:
        with st.spinner("Processando PDFs com Gemini e aplicando regras v2.1..."):
            try:
                # Obtém os bytes dos arquivos anexados
                seeu_bytes = file_seeu.read()
                bnmp_bytes = file_bnmp.read()

                # Extrai dados via Gemini API
                dados_json = extrair_dados_pdf(seeu_bytes, bnmp_bytes, api_key)

                with st.expander("🛠️ Ver Dados Estruturados (Auditoria)"):
                    st.json(dados_json)

                # Processa regras no backend Python
                cenario, texto_final = aplicar_regras_v2_1(dados_json)

                st.markdown("---")
                if cenario == "Cenário A":
                    st.success(texto_final)
                else:
                    st.error(texto_final)

            except Exception as e:
                st.error(f"Erro ao processar os arquivos PDF: {str(e)}")
