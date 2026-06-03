# =========================================================
# V29.0 - ENGINE SEMÂNTICA: ROTEAMENTO DE LAYOUT E TRAVA DE MEDIDAS
# =========================================================

import streamlit as st
import pandas as pd
import re
import unicodedata
import pdfplumber
from rapidfuzz import fuzz
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from io import BytesIO
from datetime import datetime

# =========================================================
# CONFIGURAÇÃO E ONTOLOGIA
# =========================================================

st.set_page_config(page_title="PoupaMed", layout="wide", page_icon="🩺")
st.success("✨ ENGINE V29.0 - ROTEAMENTO DE LAYOUT E TRAVA DE MEDIDAS ✨")

DEBUG_MODE = True
SCORE_MINIMO = 70 

FAMILIAS_MEDICAS = {
    "TUBO": ["VACUO", "COLETA", "GEL", "K3", "CITRATO", "EDTA", "FLUORETO"],
    "SERINGA": ["INSULINA", "BICO", "SLIP", "LOCK"],
    "AGULHA": ["HIPODERMICA", "GENGIVAL"],
    "LUVA": ["PROCEDIMENTO", "CIRURGICA", "LATEX", "NITRILICA", "VINIL"],
    "SCALP": ["ESCALPE", "BORBOLETA"],
    "SONDA": ["URETRAL", "FOLEY", "NASOGASTRICA"],
    "COLETOR": ["PERFUROCORTANTE", "URINA", "FEZES", "PERF"]
}

SINONIMOS = {
    r'\bTRI\b': 'TRIPLA',
    r'\b3 CAMADAS\b': 'TRIPLA',
    r'\bBCA\b': 'BRANCA',
    r'\bDESC\b': 'DESCARTAVEL',
    r'\bVACUTUBE\b': 'TUBO A VACUO',
    r'\bGEL SEP\b': 'GEL SEPARADOR',
    r'\bAML\b': 'AMARELO',
    r'\bPERF\b': 'PERFUROCORTANTE',
    r'\bC/\b': 'COM ',
    r'\bS/\b': 'SEM ',
    r'\bUND\b': 'UN',
    r'\bPCT\b': 'PACOTE'
}

ATRIBUTOS_MUTEX = [
    {"ADULTO", "INFANTIL", "PEDIATRICO", "NEONATAL"},
    {"ESTERIL", "NAO ESTERIL"},
    {"LATEX", "NITRILICA", "SILICONE", "VINIL"},
    {"C20", "C100", "C50", "C200"},
    {"25X7", "40X12", "13X45", "30X8"},
    {"URETRAL", "NASOGASTRICA", "ENDOTRAQUEAL"},
    {"K3", "GEL SEPARADOR", "CITRATO", "HEPARINA", "FLUORETO"}
]

MARCAS_CONHECIDAS = [
    "MEDIX", "LABOR IMPORT", "DESCARPACK", "BIOCON", "FIRSTLAB", "NEWPROV", 
    "VACUPLAST", "RENYLAB", "BD", "3M", "JOHNSON", "MEDTRONIC", "BBRAUN", "BAXTER", "CREMER", "J PROLAB"
]

STOPWORDS_MATCH = {"KIT", "CX", "UND", "UN", "ML", "MG", "G", "L", "PCT", "PARA", "COM"}
STOPWORDS_CATEGORIA = {"TUBO", "VACUTUBE", "A", "VACUO", "PARA", "COM", "DE", "DA", "DO", "EM", "E", "C", "S", "COLETOR"}

# =========================================================
# NLP E EXTRAÇÃO
# =========================================================

def normalizar_texto_basico(texto):
    texto = str(texto).upper().strip()
    texto = unicodedata.normalize('NFKD', texto)
    return ''.join(c for c in texto if not unicodedata.combining(c))

def extrair_medidas(texto):
    encontradas = re.findall(r'\b\d+[\.,]?\d*\s*(?:ML|L|MG|G|KG|MM|CM)\b', texto)
    normalizadas = set()
    for m in encontradas:
        m = m.replace(',', '.')
        m = re.sub(r'\s+', '', m) 
        m = re.sub(r'\.0+(ML|L|MG|G|KG|MM|CM)', r'\1', m)
        normalizadas.add(m)
    return normalizadas

def normalizar_produto_medico(texto):
    texto = normalizar_texto_basico(texto)
    
    texto = re.sub(r'\bC/\s*\d+\b', '', texto)
    texto = re.sub(r'\b\d+\s*UND?\b', '', texto)
    texto = re.sub(r'\bCX\s*\d+\b', '', texto)
    texto = re.sub(r'\bEMB\s*C/\d+\b', '', texto)
    
    for padrao, sub in SINONIMOS.items():
        texto = re.sub(padrao, sub, texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    
    marca_encontrada = None
    for marca in MARCAS_CONHECIDAS:
        if re.search(rf'\b{marca}\b', texto):
            marca_encontrada = marca
            texto = re.sub(rf'\b{marca}\b', '', texto).strip()
            
    medidas = extrair_medidas(texto)
    
    texto_sem_pontuacao = re.sub(r'[^A-Z0-9\s]', ' ', texto)
    atributos = set()
    for grupo in ATRIBUTOS_MUTEX:
        for attr in grupo:
            if re.search(rf'\b{attr}\b', texto_sem_pontuacao):
                atributos.add(attr)

    texto_limpo = re.sub(r'\s+', ' ', texto_sem_pontuacao).strip()
    palavras = [p for p in texto_limpo.split() if p not in STOPWORDS_MATCH]
    palavras_fortes = [p for p in palavras if p not in STOPWORDS_CATEGORIA]
    
    # NOVA REGRA: Busca primeiro na Ontologia de Famílias
    categoria = ""
    for familia, keywords in FAMILIAS_MEDICAS.items():
        if re.search(rf'\b{familia}\b', texto_limpo):
            categoria = familia
            break
        if any(re.search(rf'\b{kw}\b', texto_limpo) for kw in keywords):
            categoria = familia
            break

    # Fallback se não achar na família
    if not categoria:
        categoria = " ".join(palavras_fortes[:2]) if len(palavras_fortes) >= 2 else (palavras_fortes[0] if palavras_fortes else (palavras[0] if palavras else ""))
    
    return {
        "texto_limpo": texto_limpo,
        "categoria": categoria,
        "marca": marca_encontrada,
        "medidas": medidas,
        "atributos": atributos
    }

# =========================================================
# SCORE SEMÂNTICO V29 (TRAVA DE MEDIDAS)
# =========================================================

def calcular_score_semantico(dict_cliente, dict_forn):
    # REGRA 1 V29: Aborto imediato se medidas existirem e forem diferentes (13L != 1.5L)
    if dict_cliente["medidas"] and dict_forn["medidas"]:
        if not dict_cliente["medidas"].intersection(dict_forn["medidas"]):
            return 0
            
    for grupo in ATRIBUTOS_MUTEX:
        attr_c = grupo.intersection(dict_cliente["atributos"])
        attr_f = grupo.intersection(dict_forn["atributos"])
        if attr_c and attr_f and not attr_c.intersection(attr_f):
            return 0 
            
    score = 0
    
    if dict_cliente["categoria"] and dict_cliente["categoria"] == dict_forn["categoria"]:
        score += 40
    else:
        cat_fuzz = fuzz.ratio(dict_cliente["categoria"], dict_forn["categoria"])
        if cat_fuzz > 80:
            score += (cat_fuzz * 0.4)
        else:
            return 0 
            
    if dict_cliente["atributos"]:
        matches = len(dict_cliente["atributos"].intersection(dict_forn["atributos"]))
        total = len(dict_cliente["atributos"])
        score += (matches / total) * 20
    else:
        score += 20
        
    if dict_cliente["medidas"]:
        matches = len(dict_cliente["medidas"].intersection(dict_forn["medidas"]))
        total = len(dict_cliente["medidas"])
        score += (matches / total) * 20
    else:
        score += 20
        
    text_fuzz = fuzz.token_set_ratio(dict_cliente["texto_limpo"], dict_forn["texto_limpo"])
    score += (text_fuzz * 0.2)
    
    return score

# =========================================================
# PARSERS ESPECÍFICOS E ROTEAMENTO (V29)
# =========================================================

def converter_decimal_seguro(valor, default="0"):
    try:
        valor = str(valor).strip().upper()
        valor_limpo = re.sub(r'[A-Za-zR$\s]', '', valor)
        if not valor_limpo: return Decimal(default) if default is not None else None
        if "." in valor_limpo and "," in valor_limpo:
            if valor_limpo.rfind(',') > valor_limpo.rfind('.'):
                valor_limpo = valor_limpo.replace(".", "").replace(",", ".")
            else:
                valor_limpo = valor_limpo.replace(",", "")
        elif "," in valor_limpo:
            valor_limpo = valor_limpo.replace(",", ".")
        return Decimal(valor_limpo)
    except:
        return Decimal(default) if default is not None else None

def parse_pdf_prevena(pdf):
    # Lógica customizada para Prevena / Viveo
    # Exemplo: Procura as colunas exatas pelo nome
    todas_linhas = []
    for pagina in pdf.pages:
        tabelas = pagina.extract_tables()
        if tabelas:
            for tabela in tabelas:
                for linha in tabela:
                    linha_limpa = [str(c).replace('\n', ' ').strip() if c else "" for c in linha]
                    if any(linha_limpa): todas_linhas.append(linha_limpa)
                    
    df = pd.DataFrame(todas_linhas)
    # Rastreamento específico Prevena
    # Descrição = col 2 | Quantidade = col 4 | Unitário = col 6 | Total = col 7 (índices variam levemente, ajuste após teste)
    col_desc, col_qtd, col_preco, col_total = 2, 4, 6, 7 
    return df, col_desc, col_preco, col_qtd, None, col_total

def parse_pdf_biocon(pdf):
    # Lógica customizada para Biocon (Lida com quebras de linha em Lotes)
    todas_linhas = []
    for pagina in pdf.pages:
        tabelas = pagina.extract_tables()
        if tabelas:
            for tabela in tabelas:
                # Na Biocon, se a coluna 0 (Item) for vazia, é continuação da linha anterior!
                linha_atual = []
                for linha in tabela:
                    linha_limpa = [str(c).replace('\n', ' ').strip() if c else "" for c in linha]
                    if not any(linha_limpa): continue
                    
                    if re.match(r'^\d+$', linha_limpa[0]): # Início de novo item
                        if linha_atual: todas_linhas.append(linha_atual)
                        linha_atual = linha_limpa
                    else:
                        # Concatena a descrição quebrada
                        if linha_atual and len(linha_limpa) > 4:
                            linha_atual[4] += " " + linha_limpa[4] 
                if linha_atual: todas_linhas.append(linha_atual)
                
    df = pd.DataFrame(todas_linhas)
    # Rastreamento específico Biocon: Quantidade=1, Descrição=4, Unit=5, Total=6
    col_desc, col_qtd, col_preco, col_total = 4, 1, 5, 6
    return df, col_desc, col_preco, col_qtd, None, col_total

@st.cache_data
def roteador_e_extrator_pdf(arquivo_upload):
    try:
        arquivo_upload.seek(0)
        texto_identificacao = ""
        
        with pdfplumber.open(arquivo_upload) as pdf:
            if len(pdf.pages) > 0:
                texto_identificacao = str(pdf.pages[0].extract_text()).upper()
                
            # ETAPA 1: Detector de Layout
            if "PREVENA" in texto_identificacao or "VIVEO" in texto_identificacao:
                if DEBUG_MODE: st.info(f"🔄 Layout Detectado: PREVENA ({arquivo_upload.name})")
                df, c_desc, c_preco, c_qtd, c_ipi, c_total = parse_pdf_prevena(pdf)
                
            elif "BIOCON" in texto_identificacao:
                if DEBUG_MODE: st.info(f"🔄 Layout Detectado: BIOCON ({arquivo_upload.name})")
                df, c_desc, c_preco, c_qtd, c_ipi, c_total = parse_pdf_biocon(pdf)
                
            else:
                # Fallback Genérico V28
                if DEBUG_MODE: st.info(f"🔄 Layout Genérico ({arquivo_upload.name})")
                df = None # (Aqui entra a lógica antiga extrair_tabela_pdf_local)
                # ... (manter extração genérica caso precise) ...
                return pd.DataFrame() 

        # ETAPA 2: Retorna DataFrame bruto + mapeamento exato
        return df, c_desc, c_preco, c_qtd, c_ipi, c_total
        
    except Exception as e:
        st.error(f"Erro ao ler PDF {arquivo_upload.name}: {e}")
        return None, None, None, None, None, None

# =========================================================
# LIMPEZA E FORMATAÇÃO
# =========================================================

def limpar_tabela_padronizada(df, col_desc, col_preco, col_qtd, col_ipi, col_total):
    novas_descricoes, novos_precos, novas_qtds, novos_ipis, novos_totais_base = [], [], [], [], []

    for idx, row in df.iterrows():
        try:
            texto_desc = str(row[col_desc]).strip()
            if not texto_desc or texto_desc.lower() in ["nan", "none", ""]: continue

            quantidade = converter_decimal_seguro(row[col_qtd], "1") if col_qtd is not None else Decimal("1")
            preco_unit = converter_decimal_seguro(row[col_preco], None) if col_preco is not None else None
            preco_total_arquivo = converter_decimal_seguro(row[col_total], None) if col_total is not None else None
            ipi = converter_decimal_seguro(row[col_ipi], "0") if col_ipi is not None else Decimal("0")

            if preco_unit is None or preco_total_arquivo is None: continue

            # MATEMÁTICA PURA (BUG RESOLVIDO)
            preco_total_base = preco_unit * quantidade
            
            if abs(preco_total_base - preco_total_arquivo) <= Decimal("0.05"):
                preco_total_base = preco_total_arquivo # Aceita arredondamento do fornecedor
            else:
                preco_total_base = preco_unit * quantidade # Força matemática pura
                if DEBUG_MODE: st.warning(f"⚠️ Correção matemática aplicada na linha: {texto_desc[:30]}")

            novas_descricoes.append(texto_desc)
            novos_precos.append(preco_unit)
            novas_qtds.append(quantidade)
            novos_ipis.append(ipi) 
            novos_totais_base.append(preco_total_base)
        except Exception:
            continue

    return pd.DataFrame({
        "Descrição Limpa": novas_descricoes,
        "DICT_MATCH": [normalizar_produto_medico(x) for x in novas_descricoes],
        "Preço Unitário": novos_precos,
        "Quantidade Fornecedor": novas_qtds,
        "IPI": novos_ipis,
        "Preço Total Base": novos_totais_base
    })

def criar_indice_fornecedor(df_forn_processado):
    indice = defaultdict(list)
    for idx, row in df_forn_processado.iterrows():
        dict_match = row["DICT_MATCH"]
        palavras = dict_match["texto_limpo"].split()
        if palavras:
            indice[f"PRIMEIRA_{palavras[0]}"].append(idx)
            for palavra in palavras:
                if len(palavra) > 2:
                    indice[palavra].append(idx)
    return indice

def formatar_brl(valor):
    if valor is None: valor = Decimal("0")
    valor = valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    valor_str = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {valor_str}"

# (A função gerar_pdf_relatorio permanece idêntica a V28)
# ...

# =========================================================
# INTERFACE PRINCIPAL
# =========================================================
# (Setup Sidebar IDÊNTICO)

if arquivo_cliente and arquivos_fornecedores:
    if st.sidebar.button("🚀 GERAR COTAÇÃO", use_container_width=True, type="primary"):
        try:
            with st.spinner("Analisando PDFs e roteando layouts..."):
                # (Leitura do cliente idêntica) ...
                # (Preparo df_cliente idêntico) ...

                resultados_finais = []
                detalhes_fornecedores = {}
                cache_scores = {}

                for arq in arquivos_fornecedores:
                    cache_scores.clear() # 🚀 LIMPEZA DE MEMÓRIA (Evita estouro de RAM)
                    nome_fornecedor = arq.name.rsplit('.', 1)[0].upper()
                    
                    if arq.name.endswith(".pdf"):
                        # Nova chamada do Roteador V29
                        df_bruto, c_desc, c_preco, c_qtd, c_ipi, c_total = roteador_e_extrator_pdf(arq)
                        if df_bruto is None or df_bruto.empty: continue
                        df_forn_processado = limpar_tabela_padronizada(df_bruto, c_desc, c_preco, c_qtd, c_ipi, c_total)
                        
                    elif arq.name.endswith(".xlsx") or arq.name.endswith(".csv"):
                        # Tratar planilhas como na V28 (omitido para brevidade)
                        pass 

                    if len(df_forn_processado) == 0: continue
                    indice_fornecedor = criar_indice_fornecedor(df_forn_processado)

                    total_carrinho = Decimal("0.00")
                    itens_nao_encontrados = 0
                    itens_detalhados = []

                    for _, linha_cliente in df_cliente.iterrows():
                        # ... Logica de candidatos usando cache_scores e calcular_score_semantico ...
                        pass
                    
                    # Salva status do fornecedor ...

                # Renderiza Resultados ...
