# =========================================================
# V29.3 - ENGINE SEMÂNTICA: FORÇA BRUTA SUPERCHARGED E COSTURA DE LINHAS
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
st.success("✨ ENGINE V29.3 - FORÇA BRUTA DINÂMICA E COSTURA DE LINHAS ✨")

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
# FUNÇÕES DE LEITURA E ARQUIVOS 
# =========================================================

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
            if not linha or linha.startswith('#') or linha.startswith('//'): continue
            linha = re.sub(r'\s+', ' ', linha).strip()
            dados.append({"Produto": linha, "Quantidade": "1"})
        
        if not dados:
            st.error("Nenhum item válido encontrado no arquivo TXT")
            return None
        return pd.DataFrame(dados)
    except Exception as e:
        st.error(f"Erro ao ler arquivo TXT: {e}")
        return None

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
    
    categoria = ""
    for familia, keywords in FAMILIAS_MEDICAS.items():
        if re.search(rf'\b{familia}\b', texto_limpo):
            categoria = familia
            break
        if any(re.search(rf'\b{kw}\b', texto_limpo) for kw in keywords):
            categoria = familia
            break

    if not categoria:
        categoria = " ".join(palavras_fortes[:2]) if len(palavras_fortes) >= 2 else (palavras_fortes[0] if palavras_fortes else (palavras[0] if palavras else ""))
    
    return {
        "texto_limpo": texto_limpo,
        "categoria": categoria,
        "marca": marca_encontrada,
        "medidas": medidas,
        "atributos": atributos
    }

def converter_preco(valor):
    if pd.isna(valor): return None
    valor = str(valor).strip()
    valor = re.sub(r'[A-Za-zR$\s]', '', valor)
    if not valor: return None
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

# =========================================================
# SCORE SEMÂNTICO V29
# =========================================================

def calcular_score_semantico(dict_cliente, dict_forn):
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
# FORÇA BRUTA SUPERCHARGED (SUBSTITUI OS PARSERS FIXOS)
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
                        extraiu_algo = False
                        for tabela in tabelas:
                            for linha in tabela:
                                linha_limpa = [str(celula).replace('\n', ' ').strip() if celula else "" for celula in linha]
                                if any(linha_limpa) and len(linha_limpa) >= 2:
                                    todas_linhas.append(linha_limpa)
                                    extraiu_algo = True
                        if extraiu_algo: break # Se achou colunas validas, ignora o resto das estrategias pra essa pagina

        if not todas_linhas: return None
        
        df = pd.DataFrame(todas_linhas)
        df = df.drop_duplicates().reset_index(drop=True)
        
        idx_cabecalho = -1
        for i, row in df.iterrows():
            linha_str = " ".join(row.astype(str)).lower()
            if any(palavra in linha_str for palavra in ["descri", "produto", "item", "código", "codigo", "filial venda"]):
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
        return None

def identificar_colunas_inteligente(df, nome_arquivo):
    col_desc = col_preco = col_qtd = col_ipi = col_total = None
    
    for col in df.columns:
        col_lower = str(col).lower()
        if not col_desc and any(p in col_lower for p in ["descri", "produto", "material"]):
            col_desc = col
        if not col_preco and any(p in col_lower for p in ["preço", "preco", "valor de venda", "unitário", "unit"]):
            if "total" not in col_lower and "subunidade" not in col_lower: 
                col_preco = col
        if not col_qtd and any(p in col_lower for p in ["qtd", "qtde", "quantidade", "quant", "qde", "unid"]):
            col_qtd = col
        if not col_ipi and "ipi" in col_lower:
            col_ipi = col
        if not col_total and any(p in col_lower for p in ["preco total", "preço total", "valor total", "total"]):
            col_total = col

    # Fallback Posicional
    if len(df.columns) >= 5:
        if col_qtd is None: col_qtd = df.columns[1]
        if col_preco is None: col_preco = df.columns[-2]
        if col_total is None: col_total = df.columns[-1]
        if col_desc is None:
            max_len = 0
            for col in df.columns[2:-2]: 
                mean_len = df[col].astype(str).str.len().mean()
                if mean_len > max_len:
                    max_len = mean_len
                    col_desc = col
                    
    if DEBUG_MODE:
        st.info(f"📄 Mapeamento Identificado -> Desc={col_desc} | Preço={col_preco} | Qtd={col_qtd} | Total={col_total}")
        
    return col_desc, col_preco, col_qtd, col_ipi, col_total

def limpar_tabela_hibrida(df, col_desc_nome, col_preco_nome, col_qtd_nome=None, col_ipi_nome=None, col_total_nome=None, nome_arquivo="desconhecido"):
    novas_descricoes, novos_precos, novas_qtds, novos_ipis, novos_totais_base = [], [], [], [], []
    
    for idx, row in df.iterrows():
        if pd.isna(row[col_desc_nome]): continue
        texto_desc = str(row[col_desc_nome]).strip()
        if not texto_desc or texto_desc.lower() in ["nan", "none", ""]: continue

        preco_unit = preco_total_arquivo = None
        quantidade = Decimal("1")
        
        if col_preco_nome and pd.notna(row[col_preco_nome]):
            preco_unit = converter_preco(str(row[col_preco_nome]))
        if col_total_nome and pd.notna(row[col_total_nome]):
            preco_total_arquivo = converter_preco(str(row[col_total_nome]))

        # COSTURA DE LINHAS (Se a linha não tem preço, cola o texto na descrição do produto anterior!)
        if preco_unit is None or preco_total_arquivo is None:
            if novas_descricoes and len(texto_desc) > 2:
                novas_descricoes[-1] += " " + texto_desc
            continue

        if col_qtd_nome and pd.notna(row[col_qtd_nome]):
            qtd_val = converter_decimal_seguro(str(row[col_qtd_nome]), default=None)
            if qtd_val and qtd_val > Decimal("0"): quantidade = qtd_val

        preco_total_base = preco_unit * quantidade
        if abs(preco_total_base - preco_total_arquivo) <= Decimal("0.05"):
            preco_total_base = preco_total_arquivo
        else:
            preco_total_base = preco_total_arquivo 

        ipi = converter_decimal_seguro(str(row[col_ipi_nome]), "0") if col_ipi_nome and pd.notna(row[col_ipi_nome]) else Decimal("0")

        novas_descricoes.append(texto_desc)
        novos_precos.append(preco_unit)
        novas_qtds.append(quantidade)
        novos_ipis.append(ipi) 
        novos_totais_base.append(preco_total_base)

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

    dados_tabela = [["Status", "Item Desejado", "Produto Encontrado", "Qtd", "Preço Unit.", "Total s/ IPI", "IPI", "Total c/ IPI"]]
    for _, row in df_detalhes.iterrows():
        item_desejado = Paragraph(str(row["Item Desejado"]), style_normal)
        produto_encontrado = Paragraph(str(row["Produto Encontrado"]), style_normal)
        
        dados_tabela.append([str(row["Status"]), item_desejado, produto_encontrado, 
                            str(row["Qtd"]), str(row["Preço Unitário"]), 
                            str(row["Total s/ IPI"]), str(row["IPI"]), 
                            str(row["Total c/ IPI"])])
    
    dados_tabela.append(["", "", "", "", "", "", "TOTAL GERAL", formatar_brl(total)])

    tabela = Table(dados_tabela, repeatRows=1, colWidths=[60, 95, 95, 30, 50, 55, 30, 60])
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

DEBUG_MODE = st.sidebar.checkbox("🔧 Modo Debug (mostrar logs)", value=True)

if arquivo_cliente and arquivos_fornecedores:
    if st.sidebar.button("🚀 GERAR COTAÇÃO", use_container_width=True, type="primary"):
        try:
            with st.spinner("Analisando PDFs com Extração Dinâmica Inteligente..."):
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
                
                if not col_item_cliente:
                    st.error("Não encontrei coluna de Produto na Lista de Desejos")
                    st.stop()

                df_cliente = df_cliente.dropna(subset=[col_item_cliente])
                df_cliente["Quantidade"] = 1
                df_cliente["DICT_MATCH"] = df_cliente[col_item_cliente].astype(str).apply(normalizar_produto_medico)

                resultados_finais = []
                detalhes_fornecedores = {}
                cache_scores = {}

                for arq in arquivos_fornecedores:
                    cache_scores.clear() 
                    nome_fornecedor = arq.name.rsplit('.', 1)[0].upper()
                    contador = 1
                    nome_original = nome_fornecedor
                    while nome_fornecedor in detalhes_fornecedores:
                        nome_fornecedor = f"{nome_original}_{contador}"
                        contador += 1

                    df_forn_processado = pd.DataFrame()

                    if arq.name.endswith(".pdf"):
                        if DEBUG_MODE: st.info(f"🔄 Executando varredura dinâmica no arquivo: {arq.name}")
                        df_bruto = extrair_tabela_pdf_local(arq)
                        if df_bruto is not None and not df_bruto.empty:
                            colunas = identificar_colunas_inteligente(df_bruto, nome_fornecedor)
                            if colunas[0]:
                                df_forn_processado = limpar_tabela_hibrida(df_bruto, *colunas, nome_fornecedor)

                    elif arq.name.endswith(".xlsx"):
                        df_forn = pd.read_excel(arq)
                        df_forn.columns = df_forn.columns.astype(str).str.strip()
                        colunas = identificar_colunas_inteligente(df_forn, nome_fornecedor)
                        if colunas[0]:
                            df_forn_processado = limpar_tabela_hibrida(df_forn, *colunas, nome_fornecedor)
                    else:
                        try:
                            df_forn = pd.read_csv(arq, sep=None, engine="python", encoding='utf-8')
                        except UnicodeDecodeError:
                            arq.seek(0)
                            df_forn = pd.read_csv(arq, sep=None, engine="python", encoding='latin-1')
                        df_forn.columns = df_forn.columns.astype(str).str.strip()
                        colunas = identificar_colunas_inteligente(df_forn, nome_fornecedor)
                        if colunas[0]:
                            df_forn_processado = limpar_tabela_hibrida(df_forn, *colunas, nome_fornecedor)

                    if df_forn_processado is None or len(df_forn_processado) == 0: 
                        if DEBUG_MODE: st.error(f"❌ Falha crítica: Nenhum item salvo de {arq.name}. Tabela descartada.")
                        continue
                    
                    indice_fornecedor = criar_indice_fornecedor(df_forn_processado)

                    total_carrinho = Decimal("0.00")
                    itens_nao_encontrados = 0
                    itens_detalhados = []

                    for _, linha_cliente in df_cliente.iterrows():
                        item_original = str(linha_cliente[col_item_cliente]).strip()
                        dict_cliente = linha_cliente["DICT_MATCH"]
                        
                        candidatos_idx = set()
                        palavras_item = [p for p in dict_cliente["texto_limpo"].split() if len(p) > 2]

                        if palavras_item:
                            candidatos_idx.update(indice_fornecedor.get(f"PRIMEIRA_{palavras_item[0]}", []))
                            for palavra in palavras_item:
                                candidatos_idx.update(indice_fornecedor.get(palavra, []))

                        if not candidatos_idx:
                            candidatos_idx = range(len(df_forn_processado))

                        candidatos = []
                        for idx in candidatos_idx:
                            linha_forn = df_forn_processado.iloc[idx]
                            dict_forn = linha_forn["DICT_MATCH"]
                            
                            chave = (item_original, linha_forn["Descrição Limpa"])
                            if chave in cache_scores:
                                score = cache_scores[chave]
                            else:
                                score = calcular_score_semantico(dict_cliente, dict_forn)
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
                            status_auditoria = "✅ Confirmado" if escolhido['score'] >= 85 else "⚠️ Revisar"

                            itens_detalhados.append({
                                "Status": status_auditoria,
                                "Score": f"{escolhido['score']:.0f}",
                                "Item Desejado": item_original,
                                "Produto Encontrado": escolhido["linha"]["Descrição Limpa"],
                                "Qtd": float(qtd_fornecedor),
                                "Preço Unitário": formatar_brl(preco_unitario),
                                "Total s/ IPI": formatar_brl(preco_total_base),
                                "IPI": f"{ipi}%",
                                "Total c/ IPI": formatar_brl(subtotal_com_ipi)
                            })
                        else:
                            itens_nao_encontrados += 1
                            itens_detalhados.append({
                                "Status": "❌ Rejeitado",
                                "Score": "-",
                                "Item Desejado": item_original,
                                "Produto Encontrado": "NÃO ENCONTRADO",
                                "Qtd": 0,
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
            st.error(f"Erro ao processar cotação: {str(e)}")
            if DEBUG_MODE: st.exception(e)
else:
    st.info("💡 Faça upload da lista de desejos e dos fornecedores. Depois clique em '🚀 GERAR COTAÇÃO'.")
