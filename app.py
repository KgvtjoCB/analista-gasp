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
REGREX_NUP = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
REGREX_DATA = re.compile(r"\d{2}/\d{2}/\d{4}")

# ------------------------------------------------------------------------------
# PARSER DE PDFS VIA PDFPLUMBER (LEITURA ESTRUTURADA DE TABELAS)
# ------------------------------------------------------------------------------
def extrair_texto_seeu(file_bytes):
    """Extrai todo o texto e NUPs do relatório do SEEU."""
    texto = ""
    with pdfplumber.open(file_bytes) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                texto += t + "\n"
    return list(set(REGREX_NUP.findall(texto)))

def extrair_pecas_bnmp(file_bytes):
    """
    Varre as tabelas e linhas do BNMP 3.0 extraindo NUP, Tipo de Peça, Data e Status.
    """
    pecas = []
    with pdfplumber.open(file_bytes) as pdf:
        for page in pdf.pages:
            # Tenta extrair a tabela da página
            tabelas = page.extract_tables()
            for tabela in tabelas:
                for linha in tabela:
                    # Junta todas as células da linha em um texto limpo
                    linha_texto = " ".join([str(c) for c in linha if c is not None])
                    linha_limpa = re.sub(r"\s+", " ", linha_texto)
                    
                    nup_match = REGREX_NUP.search(linha_limpa)
                    data_match = REGREX_DATA.search(linha_limpa)
                    
                    if nup_match:
                        nup = nup_match.group(0)
                        data_str = data_match.group(0) if data_match else "01/01/1900"
                        
                        linha_lower = linha_limpa.lower()
                        nome_peca = None
                        if "mandado de prisão" in linha_lower or "mandado de prisao" in linha_lower:
                            nome_peca = "Mandado de Prisão"
                        elif "alvará" in linha_lower or "alvara" in linha_lower:
                            nome_peca = "Alvará de Soltura"
                        elif "contramandado" in linha_lower:
                            nome_peca = "Contramandado de Prisão"
                        
                        if nome_peca:
                            status = "Desconhecido"
                            if "cumprido" in linha_lower:
                                status = "Cumprido"
                            elif "pendente" in linha_lower:
                                status = "Pendente de Cumprimento"
                            elif "baixado" in linha_lower:
                                status = "Baixado"
                            elif "revogado" in linha_lower:
                                status = "Revogado"
                            elif "cancelado" in linha_lower or "excluído" in linha_lower or "excluido" in linha_lower:
                                status = "Cancelado"

                            pecas.append({
                                "nup": nup,
                                "nome_peca": nome_peca,
                                "status": status,
                                "data_emissao": data_str
                            })
                            
            # Fallback para linhas corridas de texto caso o PDF não tenha bordas de tabela
            texto_pagina = page.extract_text()
            if texto_pagina:
                linhas = texto_pagina.split("\n")
                for i, l in enumerate(linhas):
                    l_lower = l.lower()
                    nome_peca = None
                    if "mandado de prisão" in l_lower or "mandado de prisao" in l_lower:
                        nome_peca = "Mandado de Prisão"
                    elif "alvará" in l_lower or "alvara" in l_lower:
                        nome_peca = "Alvará de Soltura"
                    elif "contramandado" in l_lower:
                        nome_peca = "Contramandado de Prisão"

                    if nome_peca:
                        contexto = " ".join(linhas[max(0, i-2):min(len(linhas), i+3)])
                        contexto_limpo = re.sub(r"\s+", " ", contexto)
                        nup_match = REGREX_NUP.search(contexto_limpo)
                        data_match = REGREX_DATA.search(contexto_limpo)

                        if nup_match:
                            nup = nup_match.group(0)
                            data_str = data_match.group(0) if data_match else "01/01/1900"
                            contexto_lower = contexto_limpo.lower()
                            status = "Desconhecido"
                            if "cumprido" in contexto_lower:
                                status = "Cumprido"
                            elif "pendente" in contexto_lower:
                                status = "Pendente de Cumprimento"
                            elif "baixado" in contexto_lower:
                                status = "Baixado"
                            elif "revogado" in contexto_lower:
                                status = "Revogado"

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
# MOTOR LÓGICO DAS INSTRUÇÕES V2.1 (ESPECIFICAÇÃO RIGOROSA)
# ------------------------------------------------------------------------------
def parse_data_br(data_str):
    try:
        return datetime.datetime.strptime(data_str.strip(), "%d/%m/%Y").date()
    except Exception:
        return datetime.date.min

def analisar_impedimentos_v2_1(file_seeu, file_bnmp):
    # ETAPA 2: MAPEAMENTO DA EXECUÇÃO (Lista de Exclusão Primária)
    lista_exclusao = extrair_texto_seeu(file_seeu)

    # ETAPA 1: PROCESSAMENTO E FILTRAGEM (BNMP)
    pecas_bnmp = extrair_pecas_bnmp(file_bnmp)

    mandados_analise = []
    for p in pecas_bnmp:
        if p["nome_peca"] == "Mandado de Prisão":
            if p["status"] in ["Cumprido", "Pendente de Cumprimento"]:
                mandados_analise.append(p)

    restricoes_reais = []

    # ETAPAS 2 E 3: ANÁLISE LÓGICA E VEREDITO
    for mandado in mandados_analise:
        nup_mandado = mandado["nup"].strip()

        # REGRA DE OURO (FILTRO DE IDENTIDADE / BLOQUEIO DE FALSO POSITIVO)
        if nup_mandado in lista_exclusao:
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

    # OUTPUT EXATAMENTE CONFORME FORMATO OBRIGATÓRIO V2.1
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
                # Análise Lógica V2.1
                cenario, texto_final = analisar_impedimentos_v2_1(file_seeu, file_bnmp)

                st.markdown("---")
                if cenario == "Cenário A":
                    st.success(texto_final)
                else:
                    st.error(texto_final)

            except Exception as e:
                st.error(f"Erro ao processar os arquivos PDF: {str(e)}")
