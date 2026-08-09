import datetime
import re
import pdfplumber
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
st.caption("Motor Lógico Determinístico Anti-Alucinação (SEEU & BNMP 3.0)")

# ------------------------------------------------------------------------------
# REGEX DE NUP E DATA
# ------------------------------------------------------------------------------
REGREX_NUP_FORMATADO = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
REGREX_DATA = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")

# ------------------------------------------------------------------------------
# PARSER ROBUSTO DE PDFS
# ------------------------------------------------------------------------------
def extrair_nups_seeu(file_bytes):
    """Extrai todos os NUPs únicos presentes no relatório do SEEU."""
    texto = ""
    with pdfplumber.open(file_bytes) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                texto += t + "\n"
    
    # Normaliza e limpa NUPs
    nups = REGREX_NUP_FORMATADO.findall(texto)
    return list(set(nups))

def extrair_pecas_bnmp(file_bytes):
    """
    Extrai do BNMP 3.0 todas as peças, agrupando o texto por NUP de processo 
    para imunizar contra quebras de tabela do leitor de PDF.
    """
    texto_completo = ""
    with pdfplumber.open(file_bytes) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                texto_completo += t + "\n"

    # 1. Unifica NUPs que possam ter sido quebrados por mudança de linha
    texto_limpo = re.sub(r"(\d{7}-)\n\s*(\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})", r"\1\2", texto_completo)
    texto_limpo = re.sub(r"(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\.)\n\s*", r"\1", texto_limpo)

    # 2. Divide o texto do BNMP em blocos baseados no surgimento dos NUPs
    # Procura todas as ocorrências de NUPs no texto
    matches = list(REGREX_NUP_FORMATADO.finditer(texto_limpo))
    
    pecas = []

    for i in range(len(matches)):
        start = matches[i].start()
        # O bloco vai até o início do próximo NUP ou até o fim do texto
        end = matches[i+1].start() if i + 1 < len(matches) else len(texto_limpo)
        bloco = texto_limpo[start:end]
        bloco_lower = bloco.lower()

        nup = matches[i].group(0)

        # Identifica tipo de peça no bloco
        nome_peca = None
        if "mandado de prisão" in bloco_lower or "mandado de prisao" in bloco_lower:
            nome_peca = "Mandado de Prisão"
        elif "alvará de soltura" in bloco_lower or "alvara de soltura" in bloco_lower:
            nome_peca = "Alvará de Soltura"
        elif "contramandado" in bloco_lower:
            nome_peca = "Contramandado de Prisão"

        if nome_peca:
            # Extrai a data
            data_match = REGREX_DATA.search(bloco)
            data_str = data_match.group(0) if data_match else "01/01/1900"

            # Extrai o status da peça no bloco
            status = "Desconhecido"
            if "cumprido" in bloco_lower:
                status = "Cumprido"
            elif "pendente de cumprimento" in bloco_lower or "pendente" in bloco_lower:
                status = "Pendente de Cumprimento"
            elif "baixado" in bloco_lower:
                status = "Baixado"
            elif "revogado" in bloco_lower:
                status = "Revogado"
            elif "cancelado" in bloco_lower or "excluído" in bloco_lower or "excluido" in bloco_lower:
                status = "Cancelado"

            pecas.append({
                "nup": nup,
                "nome_peca": nome_peca,
                "status": status,
                "data_emissao": data_str
            })

    # Remove duplicatas
    pecas_unicas = []
    for p in pecas:
        if p not in pecas_unicas:
            pecas_unicas.append(p)

    return pecas_unicas

# ------------------------------------------------------------------------------
# MOTOR LÓGICO DAS INSTRUÇÕES V2.1
# ------------------------------------------------------------------------------
def parse_data_br(data_str):
    try:
        return datetime.datetime.strptime(data_str.strip(), "%d/%m/%Y").date()
    except Exception:
        return datetime.date.min

def analisar_impedimentos_v2_1(file_seeu, file_bnmp):
    # ETAPA 2: MAPEAMENTO DA EXECUÇÃO (Lista de Exclusão Primária)
    lista_exclusao = extrair_nups_seeu(file_seeu)

    # ETAPA 1: PROCESSAMENTO E FILTRAGEM (BNMP)
    pecas_bnmp = extrair_pecas_bnmp(file_bnmp)

    mandados_analise = []
    for p in pecas_bnmp:
        # 1. Filtro de Nome: Exclusivamente Mandado de Prisão
        if p["nome_peca"] == "Mandado de Prisão":
            # 2. Filtro de Status: Apenas Cumprido ou Pendente de Cumprimento
            if p["status"] in ["Cumprido", "Pendente de Cumprimento"]:
                mandados_analise.append(p)

    restricoes_reais = []

    # ETAPAS 2 E 3: ANÁLISE LÓGICA E VEREDITO
    for mandado in mandados_analise:
        nup_mandado = mandado["nup"].strip()

        # REGRA DE OURO (FILTRO DE IDENTIDADE / BLOQUEIO DE FALSO POSITIVO)
        if nup_mandado in lista_exclusao:
            # Mandado pertence à própria execução -> Desconsiderar sumariamente
            continue

        # ETAPA 3: ANÁLISE DE PROCESSO ESTRANHO (BUSCA DE CONTRA-PEÇA)
        contra_pecas = [
            p for p in pecas_bnmp
            if p["nup"].strip() == nup_mandado
            and p["nome_peca"] in ["Alvará de Soltura", "Contramandado de Prisão"]
        ]

        data_mandado = parse_data_br(mandado["data_emissao"])
        status_final = "PROVÁVEL RESTRIÇÃO"
        motivo = "Mandado de Prisão identificado em processo que **NÃO** consta no Relatório de Execução e não possui contra-peça posterior."

        if contra_pecas:
            contra_pecas.sort(key=lambda x: parse_data_br(x["data_emissao"]), reverse=True)
            data_contra = parse_data_br(contra_pecas[0]["data_emissao"])

            if data_contra > data_mandado:
                continue
            elif data_contra == data_mandado:
                status_final = "ANÁLISE MANUAL (BNMP 3.0)"
                motivo = "Mandado e Alvará/Contramandado possuem a **EXATA MESMA DATA**."

        restricoes_reais.append({
            "nup": nup_mandado,
            "status": status_final,
            "motivo": motivo,
            "data_mandado": mandado["data_emissao"],
            "status_mandado": mandado["status"]
        })

    # FORMATO DO OUTPUT OBRIGATÓRIO V2.1
    if not restricoes_reais:
        return (
            "Cenário A",
            "Análise Detalhada: **Não foram encontradas restrições impeditivas.** "
            "Todos os mandados analisados referem-se aos processos já constantes na execução atual "
            "ou possuem baixa processual clara. (Falsos positivos de Número Único foram filtrados)."
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
        st.warning("Envie ambos os arquivos PDF (SEEU e BNMP) para iniciar a análise.")
    else:
        with st.spinner("Analisando documentos via motor determinístico local..."):
            try:
                cenario, texto_final = analisar_impedimentos_v2_1(file_seeu, file_bnmp)

                st.markdown("---")
                if cenario == "Cenário A":
                    st.success(texto_final)
                else:
                    st.error(texto_final)

            except Exception as e:
                st.error(f"Erro ao processar os arquivos PDF: {str(e)}")
