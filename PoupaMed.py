# =========================================================
# V19.3 - ENGINE DE AUDITORIA: CORREÇÃO DE UI (SLIDER E UPLOAD)
# =========================================================

import streamlit as st
import pandas as pd
import re
import unicodedata
import pdfplumber
from rapidfuzz import fuzz
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from functools import lru_cache
import warnings
warnings.filterwarnings('ignore')

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from io import BytesIO
from datetime import datetime

# =========================================================
# CONFIGURAÇÃO
# =========================================================

st.set_page_config(page_title="PoupaMed", layout="wide", page_icon="🩺")
st.success("✨ ENGINE V19.3 - INTERFACE FLUIDA ✨")

# As globais agora são controladas diretamente pelos widgets na barra lateral
# (Removidas as definições estáticas daqui do topo para evitar conflitos)

# =========================================================
# CONFIGURAÇÕES DE EMBALAGEM E BLACKLIST
# =========================================================

EMBALAGENS = {
    'UN': 1, 'UNID': 1, 'UNIDADE': 1,
    'CX': 100, 'CAIXA': 100, 'CAIXAS': 100,
    'PCT': 10, 'PACOTE': 10, 'PACOTES': 10,
    'KIT': 1, 'KITS': 1,
    'PAR': 2, 'PARES': 2,
    'RL': 1, 'ROLO': 1, 'ROLOS': 1,
    'FD': 1, 'FRASCO': 1, 'FRASCOS': 1,
}

BLACKLIST_SEMANTICA = [
    ("URETRAL", "NASOGASTRICA"),
    ("ADULTO", "INFANTIL"),
    ("ESTERIL", "NAO_ESTERIL"),
    ("DESCARTAVEL", "PERMANENTE"),
    ("VENOSO", "ARTERIAL"),
    ("SILICONE", "LATEX"),
    ("C20", "C100"),
    ("25X7", "40X12"),
    ("20ML", "60ML"),
    ("LATEX", "NITRILICA"),
    ("ESTERIL", "NAO ESTERIL"),
]

PALAVRAS_CRITICAS = ["EDTA", "GEL", "CITRATO", "HEPARINA", "SERINGA", "SCALP"]

STOPWORDS_MATCH = {"KIT", "CX", "UND", "UN", "ML", "MG", "G", "L", "PCT", "PARA", "COM"}

# =========================================================
# FUNÇÕES DE LIMPEZA E TEXTO
# =========================================================

def normalizar_texto(texto):
    texto = str(texto).upper().strip()
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r'[^A-Z0-9\s]', ' ', texto)
    return re.sub(r'\s+', ' ', texto).strip()

def remover_palavras_irrelevantes(texto):
    palavras_ruins = ["MARCA", "PREMIUM", "DESCARBOX", "COM", "SEM", "C/", "S/"]
    return " ".join([p for p in texto.split() if p not in palavras_ruins])

def preparar_texto_match(texto):
    texto_limpo = remover_palavras_irrelevantes(normalizar_texto(texto))
    texto_limpo = re.sub(r'^\d+\s*', '', texto_limpo)
    return texto_limpo

def ler_lista_desejos_txt(arquivo_txt):
    try:
        conteudo = arquivo_txt.read()
        try:
            texto = conteudo.decode("utf-8")
        except UnicodeDecodeError:
            texto = conteudo.decode("latin-1")
        
        linhas = texto.splitlines()
        dados = []
        
        for linha in linhas:
            linha = linha.strip()
            if not linha or linha.startswith('#') or linha.startswith('//'):
                continue
            
            linha = re.sub(r'\s+', ' ', linha)
            match = re.match(r'(.+?)\s*[\-;:|,.]{1,2}\s*(\d+)', linha)
            
            if not match:
                match = re.match(r'(.+?)\s+(\d+)\s*$', linha)
            
            if not match:
                dados.append({"Produto": linha, "Quantidade": "1"})
            else:
                produto = match.group(1).strip()
                quantidade = match.group(2).strip()
                dados.append({"Produto": produto, "Quantidade": quantidade})
        
        if not dados:
            st.error("Nenhum item válido encontrado no arquivo TXT")
            return None
            
        return pd.DataFrame(dados)
        
    except Exception as e:
        st.error(f"Erro ao ler arquivo TXT: {e}")
        return None

# =========================================================
# CONVERSÃO E MEDIDAS
# =========================================================

def converter_preco(valor):
    if pd.isna(valor): return None
    valor = str(valor).strip()
    if valor in ["", "nan", "None", "NaN"]: return None
    
    valor = valor.replace("R$", "").replace(" ", "")
    
    try:
        if "," in valor and "." in valor:
            if valor.rfind(',') > valor.rfind('.'):
                valor = valor.replace(".", "").replace(",", ".")
            else:
                valor = valor.replace(",", "")
        elif "," in valor:
            valor = valor.replace(",", ".")
        
        preco = Decimal(valor)
        if preco > 100000: return None
        return preco
    except:
        return None

def formatar_brl(valor):
    if valor is None: valor = Decimal("0")
    valor = valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    valor_str = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {valor_str}"

def converter_decimal_seguro(valor, default="0"):
    try:
        valor = str(valor).strip().upper().replace(" ", "")
        valor_limpo = re.sub(r'[^0-9,\.]', '', valor)
        
        if not valor_limpo: return Decimal(default)

        if "." in valor_limpo and "," in valor_limpo:
            valor_limpo = valor_limpo.replace(".", "").replace(",", ".")
        elif "," in valor_limpo:
            valor_limpo = valor_limpo.replace(",", ".")

        return Decimal(valor_limpo)
    except:
        return Decimal(default)

def extrair_ipi_texto(texto):
    texto = normalizar_texto(texto)
    match = re.search(r'IPI\s*(\d+[\,\.]?\d*)\s*%', texto)
    if match:
        return converter_decimal_seguro(match.group(1))
    return Decimal("0")

def extrair_medida(texto):
    match = re.search(r'(\d+[\,\.]?\d*)\s*(ML|L|MG|G|KG|MM|CM)', normalizar_texto(texto))
    return f"{match.group(1)}{match.group(2)}" if match else None

def extrair_embalagem(texto):
    texto_norm = normalizar_texto(texto)
    palavras = texto_norm.split()
    for i, palavra in enumerate(palavras):
        if palavra in EMBALAGENS:
            if i > 0 and palavras[i-1].isdigit():
                return f"{palavras[i-1]}{palavra}", EMBALAGENS[palavra] * int(palavras[i-1])
            return palavra, EMBALAGENS[palavra]
    return None, None

def extrair_marca(texto):
    marcas_conhecidas = ["BD", "3M", "JOHNSON", "MEDTRONIC", "BBRAUN", "BAXTER"]
    for marca in marcas_conhecidas:
        if marca in normalizar_texto(texto):
            return marca
    return None

# =========================================================
# SCORE COMPOSTO
# =========================================================

def verificar_blacklist(texto1, texto2):
    texto1_norm = normalizar_texto(texto1)
    texto2_norm = normalizar_texto(texto2)
    for grupo1, grupo2 in BLACKLIST_SEMANTICA:
        if (grupo1 in texto1_norm and grupo2 in texto2_norm) or \
           (grupo2 in texto1_norm and grupo1 in texto2_norm):
            return True
    return False

@lru_cache(maxsize=10000)
def calcular_score_rapidfuzz(texto1, texto2):
    score1 = fuzz.token_sort_ratio(texto1, texto2)
    score2 = fuzz.token_set_ratio(texto1, texto2)
    score3 = fuzz.partial_ratio(texto1, texto2)
    return max(score1, score2, score3)

def calcular_score_composto(item_cliente, item_fornecedor, texto_cliente, texto_fornecedor):
    texto_cliente_norm = normalizar_texto(texto_cliente)
    texto_fornecedor_norm = normalizar_texto(texto_fornecedor)

    score_textual = calcular_score_rapidfuzz(item_cliente, item_fornecedor)

    for palavra in PALAVRAS_CRITICAS:
        if palavra in texto_cliente_norm and palavra not in texto_fornecedor_norm:
            score_textual -= 20

    palavras_cliente = set(item_cliente.split())
    palavras_fornecedor = set(item_fornecedor.split())
    palavras_comuns = len(palavras_cliente.intersection(palavras_fornecedor))

    if palavras_comuns > 0:
        bonus_palavras = min(20, palavras_comuns * 5)
        score_textual = min(100, score_textual + bonus_palavras)

    medida_cliente = extrair_medida(texto_cliente)
    medida_fornecedor = extrair_medida(texto_fornecedor)

    score_medida = 0
    if not medida_cliente: score_medida = 15
    elif medida_cliente == medida_fornecedor: score_medida = 15
    elif medida_cliente and medida_fornecedor: score_medida = -30

    emb_cliente, qtd_cliente = extrair_embalagem(texto_cliente)
    emb_fornecedor, qtd_fornecedor = extrair_embalagem(texto_fornecedor)

    score_embalagem = 0
    if not emb_cliente: score_embalagem = 10
    elif emb_cliente == emb_fornecedor: score_embalagem = 10
    elif emb_cliente and emb_fornecedor: score_embalagem = -10

    marca_cliente = extrair_marca(texto_cliente)
    marca_fornecedor = extrair_marca(texto_fornecedor)

    score_marca = 0
    if not marca_cliente: score_marca = 5
    elif marca_cliente == marca_fornecedor: score_marca = 5

    score_final = (score_textual * 0.7) + score_medida + score_embalagem + score_marca
    return max(0, min(score_final, 100))

# =========================================================
# MOTORES DE EXTRAÇÃO E LIMPEZA
# =========================================================

@st.cache_data
def extrair_tabela_pdf_local(arquivo_upload):
    try:
        todas_linhas = []
        arquivo_upload.seek(0)
        
        with pdfplumber.open(arquivo_upload) as pdf:
            for pagina in pdf.pages:
                for estrategia in ["text", "lines", "decimals"]:
                    tabelas = pagina.extract_tables(table_settings={
                        "vertical_strategy": estrategia, 
                        "horizontal_strategy": "text"
                    })
                    
                    if tabelas:
                        for tabela in tabelas:
                            for linha in tabela:
                                linha_limpa = [str(celula).replace('\n', ' ').strip() if celula else "" for celula in linha]
                                if any(linha_limpa) and len(linha_limpa) >= 2:
                                    todas_linhas.append(linha_limpa)
                        break

        if not todas_linhas: return None
        
        df = pd.DataFrame(todas_linhas)
        df = df.drop_duplicates().reset_index(drop=True)
        
        idx_cabecalho = -1
        for i, row in df.iterrows():
            linha_str = " ".join(row.astype(str)).lower()
            if any(palavra in linha_str for palavra in ["descri", "produto", "item", "código", "codigo"]):
                idx_cabecalho = i
                break
        
        if idx_cabecalho == -1: return df
        
        colunas_brutas = df.iloc[idx_cabecalho].astype(str).str.strip().tolist()
        colunas_tratadas = []
        contagem = {}
        
        for col in colunas_brutas:
            if not col or col.lower() in ["none", "nan", ""]: col = "COLUNA_VAZIA"
            if col in contagem:
                contagem[col] += 1
                colunas_tratadas.append(f"{col}_{contagem[col]}")
            else:
                contagem[col] = 0
                colunas_tratadas.append(col)
                
        df.columns = colunas_tratadas
        return df.iloc[idx_cabecalho+1:].reset_index(drop=True)

    except Exception as e:
        st.error(f"Erro ao ler PDF: {e}")
        return None

def identificar_colunas_inteligente(df, nome_arquivo):
    col_desc = col_preco = col_qtd = col_ipi = col_total = None

    for col in df.columns:
        col_lower = str(col).lower()
        if any(p in col_lower for p in ["descri", "produto", "item", "material"]):
            col_desc = col
        if any(p in col_lower for p in ["preço", "preco", "valor", "unit"]):
            if "total" not in col_lower: 
                col_preco = col
        if any(p in col_lower for p in ["qtd", "quantidade"]):
            col_qtd = col
        if "ipi" in col_lower:
            col_ipi = col
        if any(p in col_lower for p in ["preco total", "preço total", "valor total", "total"]):
            col_total = col

    if not col_desc:
        for col in df.columns:
            if df[col].astype(str).str.len().mean() > 10:
                col_desc = col
                break

    if DEBUG_MODE:
        st.info(f"📄 {nome_arquivo}: Desc={col_desc} | Preço={col_preco} | Qtd={col_qtd} | IPI={col_ipi} | Total Nativo={col_total}")

    return col_desc, col_preco, col_qtd, col_ipi, col_total

def limpar_tabela_hibrida(df, col_desc_nome, col_preco_nome, col_qtd_nome=None, col_ipi_nome=None, col_total_nome=None, nome_arquivo="desconhecido"):
    novas_descricoes = []
    novos_precos = []
    novas_qtds = []
    novos_ipis = [] 
    novos_totais_base = [] 

    for _, row in df.iterrows():
        texto_desc = str(row[col_desc_nome]).strip()
        if not texto_desc or texto_desc.lower() in ["nan", "none", ""]: continue

        valor_preco = str(row[col_preco_nome]).strip() if col_preco_nome else ""
        valor_preco = valor_preco.replace(" ", "") 
        
        multiplos_precos = re.findall(r'\d{1,}(?:[.,]\d{3})*(?:[.,]\d+)?', valor_preco)
        if len(multiplos_precos) >= 2: valor_preco = multiplos_precos[0]

        preco_unit = converter_preco(valor_preco)

        if preco_unit is None:
            texto_desc_limpo = texto_desc.replace(" ", "")
            numeros = re.findall(r'\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\b', texto_desc_limpo)
            if numeros:
                numero = numeros[-1]
                preco_teste = converter_preco(numero)
                if preco_teste:
                    desc_sem_preco = re.sub(r'\s*\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\b\s*$', '', texto_desc)
                    texto_desc = desc_sem_preco.strip()
                    preco_unit = preco_teste

        if preco_unit is None: continue

        quantidade = Decimal("1")
        if col_qtd_nome:
            quantidade = converter_decimal_seguro(row[col_qtd_nome], "1")

        ipi = Decimal("0")
        if col_ipi_nome:
            ipi = converter_decimal_seguro(row[col_ipi_nome], "0")
        else:
            ipi = extrair_ipi_texto(texto_desc)

        preco_total_base = None
        match_reconciliacao = False

        # ✨ RECONCILIAÇÃO MATEMÁTICA EXTREMA ✨
        linha_completa = " ".join(row.astype(str)).replace("nan", "").replace("None", "")
        linha_limpa_numeros = re.sub(r'(\d)\s+([.,]?\d)', r'\1\2', linha_completa)
        linha_limpa_numeros = re.sub(r'(\d)\s+([.,]?\d)', r'\1\2', linha_limpa_numeros) 
        
        valores_monetarios = re.findall(r'\b\d{1,}(?:[.,]\d{3})*(?:[.,]\d{2,6})?\b', linha_limpa_numeros)
        
        valores_decimais = []
        for v in valores_monetarios:
            v_dec = converter_preco(v)
            if v_dec and v_dec > 0:
                valores_decimais.append(v_dec)
                
        if preco_unit and preco_unit > Decimal("0"):
            for val in reversed(valores_decimais):
                divisao = val / preco_unit
                div_round = divisao.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                
                if div_round > 0 and abs(divisao - div_round) < Decimal("0.05") and val >= preco_unit:
                    quantidade = div_round
                    preco_total_base = val
                    match_reconciliacao = True
                    break

        if not match_reconciliacao:
            if col_total_nome:
                preco_total_arquivo = converter_preco(str(row[col_total_nome]).replace(" ", ""))
                if preco_total_arquivo:
                    preco_total_base = preco_total_arquivo
                    if preco_unit > Decimal("0"):
                        qtd_reversa = (preco_total_base / preco_unit).quantize(Decimal("0.00"), rounding=ROUND_HALF_UP).normalize()
                        quantidade = qtd_reversa
            
            if preco_total_base is None:
                preco_total_base = preco_unit * quantidade

        novas_descricoes.append(texto_desc)
        novos_precos.append(preco_unit)
        novas_qtds.append(quantidade)
        novos_ipis.append(ipi) 
        novos_totais_base.append(preco_total_base)

    df_resultado = pd.DataFrame({
        "Descrição Limpa": novas_descricoes,
        "Descrição Match": [preparar_texto_match(x) for x in novas_descricoes],
        "Preço Unitário": novos_precos,
        "Quantidade Fornecedor": novas_qtds,
        "IPI": novos_ipis,
        "Preço Total Base": novos_totais_base
    })

    return df_resultado

def criar_indice_fornecedor(df_forn_processado):
    indice = defaultdict(list)
    for idx, row in df_forn_processado.iterrows():
        palavras = str(row["Descrição Match"]).split()
        if palavras:
            indice[f"PRIMEIRA_{palavras[0]}"].append(idx)
            for palavra in palavras:
                if len(palavra) > 2:
                    indice[palavra].append(idx)
    return indice

# =========================================================
# GERAÇÃO DE PDF
# =========================================================

def gerar_pdf_relatorio(nome_fornecedor, total, itens_faltando, df_detalhes):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20, leftMargin=20, topMargin=30, bottomMargin=30)
    elementos = []
    
    styles = getSampleStyleSheet()
    style_normal = styles['BodyText']
    style_normal.fontSize = 8

    elementos.append(Paragraph("<b>RELATÓRIO DE COTAÇÃO HOSPITALAR</b>", styles['Title']))
    elementos.append(Spacer(1, 12))
    
    data_hora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    info = Paragraph(
        f"<b>Fornecedor:</b> {nome_fornecedor}<br/>"
        f"<b>Total da Cotação:</b> {formatar_brl(total)}<br/>"
        f"<b>Itens Não Encontrados:</b> {itens_faltando}<br/>"
        f"<b>Data:</b> {data_hora}", styles['BodyText']
    )
    elementos.append(info)
    elementos.append(Spacer(1, 20))

    dados_tabela = [["Item Desejado", "Produto Encontrado", "Compat.", "Qtd", "Preço Unit.", "Total s/ IPI", "IPI", "Total c/ IPI"]]
    for _, row in df_detalhes.iterrows():
        item_desejado = Paragraph(str(row["Item Desejado"]), style_normal)
        produto_encontrado = Paragraph(str(row["Produto Encontrado"]), style_normal)
        
        dados_tabela.append([item_desejado, produto_encontrado, 
                            str(row["Compatibilidade"]), str(row["Qtd"]), 
                            str(row["Preço Unitário"]), str(row["Total s/ IPI"]), 
                            str(row["IPI"]), str(row["Total c/ IPI"])])
    
    dados_tabela.append(["", "", "", "", "", "", "TOTAL GERAL", formatar_brl(total)])

    tabela = Table(dados_tabela, repeatRows=1, colWidths=[110, 110, 45, 35, 55, 60, 30, 65])
    ultima_linha = len(dados_tabela) - 1
    tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1f4e78")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 1), (-1, -2), colors.white),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, ultima_linha), (-1, ultima_linha), colors.HexColor("#d9ead3")),
        ('FONTNAME', (0, ultima_linha), (-1, ultima_linha), 'Helvetica-Bold'),
    ]))

    elementos.append(tabela)
    doc.build(elementos)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf

# =========================================================
# INTERFACE PRINCIPAL E SIDEBAR
# =========================================================

st.sidebar.header("📋 Passo 1")
arquivo_cliente = st.sidebar.file_uploader("Lista de Desejos", type=['xlsx', 'csv', 'txt'], key="cliente")

st.sidebar.header("🏢 Passo 2")
arquivos_fornecedores = st.sidebar.file_uploader("Planilhas e PDFs dos Fornecedores", 
                                                 type=['xlsx', 'csv', 'txt', 'pdf'], 
                                                 accept_multiple_files=True, key="fornecedores")

# ✅ SOLUÇÃO DO BUG DA INTERFACE AQUI
DEBUG_MODE = st.sidebar.checkbox("🔧 Modo Debug (mostrar logs)", value=True)
SCORE_MINIMO = st.sidebar.slider("🎯 Score mínimo para match", 20, 100, 72, 5)

if arquivo_cliente and arquivos_fornecedores:
    if st.sidebar.button("🚀 GERAR COTAÇÃO", use_container_width=True, type="primary"):
        try:
            with st.spinner("Extraindo e processando dados comerciais..."):
                if arquivo_cliente.name.endswith(".xlsx"):
                    df_cliente = pd.read_excel(arquivo_cliente)
                elif arquivo_cliente.name.endswith(".txt"):
                    df_cliente = ler_lista_desejos_txt(arquivo_cliente)
                    if df_cliente is None: st.stop()
                else:
                    df_cliente = pd.read_csv(arquivo_cliente, sep=None, engine="python")

                df_cliente.columns = df_cliente.columns.astype(str).str.strip()
                df_cliente = df_cliente.loc[:, ~df_cliente.columns.duplicated()].copy()

                col_item_cliente = next((c for c in df_cliente.columns if any(palavra in c.lower() for palavra in ["descri", "produto", "item"])), None)
                col_qtd_cliente = next((c for c in df_cliente.columns if any(palavra in c.lower() for palavra in ["qtd", "quant"])), None)

                if not col_item_cliente:
                    st.error("Não encontrei coluna de Produto")
                    st.stop()

                df_cliente = df_cliente.dropna(subset=[col_item_cliente])
                
                if col_qtd_cliente:
                    df_cliente["Quantidade"] = pd.to_numeric(df_cliente[col_qtd_cliente], errors="coerce").fillna(1)
                else:
                    df_cliente["Quantidade"] = 1

                df_cliente["ITEM_MATCH"] = df_cliente[col_item_cliente].astype(str).apply(preparar_texto_match)

                resultados_finais = []
                detalhes_fornecedores = {}
                cache_scores = {}

                for arq in arquivos_fornecedores:
                    nome_fornecedor = arq.name.rsplit('.', 1)[0].upper()
                    contador = 1
                    nome_original = nome_fornecedor
                    while nome_fornecedor in detalhes_fornecedores:
                        nome_fornecedor = f"{nome_original}_{contador}"
                        contador += 1

                    if arq.name.endswith(".xlsx"):
                        df_forn = pd.read_excel(arq)
                    elif arq.name.endswith(".pdf"):
                        df_forn = extrair_tabela_pdf_local(arq)
                        if df_forn is None: continue
                    else:
                        try:
                            df_forn = pd.read_csv(arq, sep=None, engine="python", encoding='utf-8')
                        except UnicodeDecodeError:
                            arq.seek(0)
                            df_forn = pd.read_csv(arq, sep=None, engine="python", encoding='latin-1')

                    df_forn.columns = df_forn.columns.astype(str).str.strip()
                    df_forn = df_forn.loc[:, ~df_forn.columns.duplicated()].copy()

                    colunas = identificar_colunas_inteligente(df_forn, nome_fornecedor)
                    if not colunas[0]: continue 

                    df_forn_processado = limpar_tabela_hibrida(df_forn, *colunas, nome_fornecedor)
                    if len(df_forn_processado) == 0: continue
                    
                    indice_fornecedor = criar_indice_fornecedor(df_forn_processado)

                    total_carrinho = Decimal("0.00")
                    itens_nao_encontrados = 0
                    itens_detalhados = []

                    for _, linha_cliente in df_cliente.iterrows():
                        item_original = str(linha_cliente[col_item_cliente]).strip()
                        item_match = linha_cliente["ITEM_MATCH"]
                        qtd_cliente = Decimal(str(round(float(linha_cliente["Quantidade"]), 4)))

                        candidatos_idx = set()
                        palavras_item = [p for p in item_match.split() if p not in STOPWORDS_MATCH and len(p) > 2]

                        if palavras_item:
                            candidatos_idx.update(indice_fornecedor.get(f"PRIMEIRA_{palavras_item[0]}", []))
                            for palavra in palavras_item:
                                candidatos_idx.update(indice_fornecedor.get(palavra, []))

                        if not candidatos_idx:
                            candidatos_idx = range(len(df_forn_processado))

                        candidatos = []
                        for idx in candidatos_idx:
                            linha_forn = df_forn_processado.iloc[idx]
                            if verificar_blacklist(item_original, linha_forn["Descrição Limpa"]): continue
                            
                            chave = (item_match, linha_forn["Descrição Match"])
                            if chave in cache_scores:
                                score = cache_scores[chave]
                            else:
                                score = calcular_score_composto(item_match, linha_forn["Descrição Match"], item_original, linha_forn["Descrição Limpa"])
                                cache_scores[chave] = score
                            
                            if score >= SCORE_MINIMO:
                                candidatos.append({"linha": linha_forn, "score": score, "preco_base": linha_forn["Preço Total Base"]})

                        if candidatos:
                            candidatos = sorted(candidatos, key=lambda x: (-x["score"], x["preco_base"]))
                            escolhido = candidatos[0]
                            
                            qtd_fornecedor = Decimal(str(escolhido["linha"]["Quantidade Fornecedor"]))
                            ipi = Decimal(str(escolhido["linha"]["IPI"]))
                            preco_total_base = Decimal(str(escolhido["linha"]["Preço Total Base"]))
                            preco_unitario = Decimal(str(escolhido["linha"]["Preço Unitário"]))

                            subtotal_com_ipi = preco_total_base * (Decimal("1") + (ipi / Decimal("100")))
                            subtotal_com_ipi = subtotal_com_ipi.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                            total_carrinho += subtotal_com_ipi

                            itens_detalhados.append({
                                "Item Desejado": item_original,
                                "Produto Encontrado": escolhido["linha"]["Descrição Limpa"],
                                "Compatibilidade": f"{escolhido['score']:.0f}%",
                                "Qtd": float(qtd_fornecedor),
                                "Preço Unitário": formatar_brl(preco_unitario),
                                "Total s/ IPI": formatar_brl(preco_total_base),
                                "IPI": f"{ipi}%",
                                "Total c/ IPI": formatar_brl(subtotal_com_ipi)
                            })
                        else:
                            itens_nao_encontrados += 1
                            itens_detalhados.append({
                                "Item Desejado": item_original,
                                "Produto Encontrado": "❌ NÃO ENCONTRADO",
                                "Compatibilidade": "0%",
                                "Qtd": float(qtd_cliente),
                                "Preço Unitário": "R$ 0,00",
                                "Total s/ IPI": "R$ 0,00",
                                "IPI": "0%",
                                "Total c/ IPI": "R$ 0,00"
                            })

                    resultados_finais.append({"Fornecedor": nome_fornecedor, "Total": total_carrinho, "Itens Faltando": itens_nao_encontrados})
                    detalhes_fornecedores[nome_fornecedor] = pd.DataFrame(itens_detalhados)

                if resultados_finais:
                    df_resultados = pd.DataFrame(resultados_finais)
                    df_resultados["Total_Ordenacao"] = df_resultados["Total"].apply(lambda x: float(x))
                    df_resultados = df_resultados.sort_values(by=["Itens Faltando", "Total_Ordenacao"]).reset_index(drop=True)

                    st.markdown("## 🏆 Resultado da Cotação")
                    cols = st.columns(min(len(df_resultados), 4))
                    melhor_fornecedor = df_resultados.iloc[0]
                    melhor_total = melhor_fornecedor["Total"]
                    
                    for i, row in df_resultados.head(4).iterrows():
                        with cols[i]:
                            if i == 0:
                                st.metric(label=f"🥇 {row['Fornecedor']}", value=formatar_brl(row["Total"]), delta=f"{row['Itens Faltando']} itens faltando")
                            else:
                                diferenca = row['Total'] - melhor_total
                                st.metric(label=row["Fornecedor"], value=formatar_brl(row["Total"]), delta=f"{'+' if diferenca >= 0 else ''}{formatar_brl(diferenca)}", delta_color="inverse")

                    alertas_fracionados = []
                    for i, row in df_resultados.iterrows():
                        if i > 0 and row["Total"] < melhor_total:
                            economia = melhor_total - row["Total"]
                            alertas_fracionados.append(
                                f"**{row['Fornecedor']}** está **{formatar_brl(economia)} mais barato**, mas deixou de cotar **{row['Itens Faltando']} item(ns)**."
                            )
                    
                    if alertas_fracionados:
                        st.warning("⚠️ **Alerta de Oportunidade (Possível Compra Fracionada):**")
                        for alerta in alertas_fracionados:
                            st.write(f"- {alerta}")
                        st.info("💡 *A plataforma deu a vitória para a empresa com a lista mais completa, mas avalie se não vale a pena fazer uma compra separada!*")

                    st.write("---")
                    st.markdown("## 🔍 Auditoria Inteligente")
                    fornecedor_select = st.selectbox("Escolha a empresa para auditar:", df_resultados["Fornecedor"].tolist())
                    df_auditoria = detalhes_fornecedores[fornecedor_select]
                    st.dataframe(df_auditoria, use_container_width=True)

                    st.write("---")
                    st.markdown("## 📄 Exportação de Relatórios PDF")
                    fornecedor_pdf = st.selectbox("Escolha o fornecedor para gerar PDF:", df_resultados["Fornecedor"].tolist(), key="pdf_select")
                    linha_pdf = df_resultados[df_resultados["Fornecedor"] == fornecedor_pdf].iloc[0]
                    pdf_bytes = gerar_pdf_relatorio(fornecedor_pdf, linha_pdf["Total"], linha_pdf["Itens Faltando"], detalhes_fornecedores[fornecedor_pdf])

                    st.download_button(label="📥 Baixar Relatório PDF", data=pdf_bytes, file_name=f"relatorio_{fornecedor_pdf}.pdf", mime="application/pdf")

        except Exception as e:
            st.error(f"Erro ao processar: {str(e)}")
            if DEBUG_MODE: st.exception(e)
else:
    st.info("💡 Faça upload da lista de desejos e dos fornecedores. Depois clique em '🚀 GERAR COTAÇÃO'.")
