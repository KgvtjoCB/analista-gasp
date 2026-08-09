import datetime
import re
import pypdf
import streamlit as st

# ------------------------------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="GASP | Analista Jurídico v2.1",
    page_icon="⚖️",
    layout="wide",
)

st.title("⚖️ Analista Jurídico (v2.1) — Filtro de Impedimentos")
st.caption("Motor Lógico Puramente Determinístico (Sem dependência de API Externa)")

# ------------------------------------------------------------------------------
# EXTRAÇÃO DE TEXTO E REGEX PARA NUPS E PEÇAS
# ------------------------------------------------------------------------------
REGREX_NUP = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
REGREX_DATA = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")


def extrair_texto_pdf(file_bytes):
    reader = pypdf.PdfReader(file_bytes)
    texto = ""
    for page in reader.pages:
        t = page.extract_text()
        if t:
            texto += t + "\n"
    return texto


def extrair_nups(texto):
    """Extrai todos os NUPs únicos no padrão CNJ mantendo a pontuação."""
    return list(set(REGREX_NUP.findall(texto)))


def extrair_pecas_bnmp(texto_bnmp):
    """
    Variação de parser para extrair registros do BNMP 3.0 via linhas de texto.
    Procura por blocos de Mandados de Prisão, Alvarás e Contramandados.
    """
    linhas = texto_bnmp.split("\n")
    pecas = []

    for i, linha in enumerate(linhas):
        nup_match = REGREX_NUP.search(linha)
        data_match = REGREX_DATA.search(linha)

        # Mapeamento do tipo de peça
        linha_lower = linha.lower()
        nome_peca = None

        if "mandado de prisão" in linha_lower or "mandado de prisao" in linha_lower:
            nome_peca = "Mandado de Prisão"
        elif "alvará" in linha_lower or "alvara" in linha_lower:
            nome_peca = "Alvará de Soltura"
        elif "contramandado" in linha_lower:
            nome_peca = "Contramandado de Prisão"

        if nome_peca and nup_match:
            nup = nup_match.group(0)
            data_str = data_match.group(0) if data_match else "01/01/1900"

            # Identifica status
            status = "Pendente de Cumprimento"
            if "cumprido" in linha_lower:
                status = "Cumprido"
            elif "baixado" in linha_lower or "revogado" in linha_lower:
                status = "Baixado"

            pecas.append(
                {
                    "nup": nup,
                    "nome_peca": nome_peca,
                    "status": status,
                    "data_emissao": data_str,
                }
            )

    return pecas


# ------------------------------------------------------------------------------
# MOTOR LÓGICO DAS INSTRUÇÕES V2.1 (CONFORME ESPECIFICAÇÃO)
# ------------------------------------------------------------------------------
def parse_data_br(data_str):
    try:
        return datetime.datetime.strptime(data_str.strip(), "%d/%m/%Y").date()
    except Exception:
        return datetime.date.min


def analisar_impedimentos_v2_1(texto_seeu, texto_bnmp):
    # ETAPA 2: MAPEAMENTO DA EXECUÇÃO (Lista de Exclusão Primária)
    lista_exclusao = extrair_nups(texto_seeu)

    # ETAPA 1: PROCESSAMENTO E FILTRAGEM (BNMP)
    pecas_bnmp = extrair_pecas_bnmp(texto_bnmp)

    mandados_analise = []
    for p in pecas_bnmp:
        if p["nome_peca"] == "Mandado de Prisão":
            # Filtro de Status: Apenas Cumprido ou Pendente
            if p["status"] in ["Cumprido", "Pendente de Cumprimento"]:
                mandados_analise.append(p)

    restricoes_reais = []

    # ETAPAS 2 E 3: ANÁLISE LÓGICA E VEREDITO
    for mandado in mandados_analise:
        nup_mandado = mandado["nup"].strip()

        # REGRA DE OURO (FILTRO DE IDENTIDADE / BLOQUEIO DE FALSO POSITIVO)
        if nup_mandado in lista_exclusao:
            # Mandado pertence à própria execução -> IGNORAR SUMARIAMENTE
            continue

        # ETAPA 3: PROCESSO ESTRANHO À EXECUÇÃO (VERIFICAÇÃO DE CONTRA-PEÇA)
        contra_pecas = [
            p
            for p in pecas_bnmp
            if p["nup"].strip() == nup_mandado
            and p["nome_peca"] in ["Alvará de Soltura", "Contramandado de Prisão"]
        ]

        data_mandado = parse_data_br(mandado["data_emissao"])
        status_final = "PROVÁVEL RESTRIÇÃO"
        motivo = "Mandado de Prisão identificado em processo que **NÃO** consta no Relatório de Execução e não possui contra-peça posterior."

        if contra_pecas:
            # Pega a contra-peça mais recente
            contra_pecas.sort(
                key=lambda x: parse_data_br(x["data_emissao"]), reverse=True
            )
            data_contra = parse_data_br(contra_pecas[0]["data_emissao"])

            if data_contra > data_mandado:
                # Contra-peça posterior liberou o processo externo
                continue
            elif data_contra == data_mandado:
                status_final = "ANÁLISE MANUAL (BNMP 3.0)"
                motivo = "Mandado e Alvará/Contramandado possuem a **EXATA MESMA DATA**."

        restricoes_reais.append(
            {
                "nup": nup_mandado,
                "status": status_final,
                "motivo": motivo,
                "data_mandado": mandado["data_emissao"],
                "status_mandado": mandado["status"],
            }
        )

    # OUTPUT EXATAMENTE CONFORME FORMATO OBRIGATÓRIO V2.1
    if not restricoes_reais:
        return (
            "Cenário A",
            "Análise Detalhada: **Não foram encontradas restrições impeditivas.** "
            "Todos os mandados analisados referem-se aos processos já constantes na execução atual "
            "ou possuem baixa processual clara. (Falsos positivos de Número Único foram filtrados).",
        )
    else:
        r = restricoes_reais[0]
        texto_cenario_b = f"""Análise Detalhada: **Foi encontrada uma restrição externa que impede a progressão/soltura.**

---
### Detalhamento do Processo Nº {r['nup']}
**Status da Análise:** [{r['status']}]

**Motivo:** {r['motivo']}

**Análise Cronológica:**
* {r['data_mandado']} - Mandado de Prisão - {r['status_mandado']}

**Ação Necessária:** Consultar processo de origem para verificar se a ordem de prisão ainda subsiste ou se houve omissão de baixa no BNMP."""
        return "Cenário B", texto_cenario_b


# ------------------------------------------------------------------------------
# INTERFACE GRÁFICA
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
    if not file_seeu or not file_bnmp:
        st.warning(
            "Envie ambos os arquivos PDF (SEEU e BNMP) para iniciar a análise."
        )
    else:
        with st.spinner("Analisando documentos via motor determinístico local..."):
            try:
                # Extração de texto dos PDFs
                texto_seeu = extrair_texto_pdf(file_seeu)
                texto_bnmp = extrair_texto_pdf(file_bnmp)

                # Análise Lógica V2.1
                cenario, texto_final = analisar_impedimentos_v2_1(
                    texto_seeu, texto_bnmp
                )

                st.markdown("---")
                if cenario == "Cenário A":
                    st.success(texto_final)
                else:
                    st.error(texto_final)

            except Exception as e:
                st.error(f"Erro ao processar os arquivos PDF: {str(e)}")
