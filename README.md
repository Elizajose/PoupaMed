PoupaMed - Engine Inteligente de Comparação Hospitalar
O PoupaMed é uma solução de automação focada em compras hospitalares, projetada para processar, auditar e comparar propostas comerciais de fornecedores. Ele transforma cotações complexas (PDFs e planilhas) em um ranking financeiro preciso, eliminando o trabalho manual e erros de digitação.

🚀 Funcionalidades Principais
Extração Inteligente: Converte PDFs de cotações (mesmo sem formatação tabular) e planilhas em dados estruturados.

Engine de Matching: Utiliza algoritmos de similaridade (RapidFuzz) e validação semântica para comparar a "Lista de Desejos" do cliente com o catálogo do fornecedor.

Cálculo Financeiro Preciso: Processamento utilizando aritmética decimal (Decimal) para garantir precisão de centavos em todas as operações, evitando erros de arredondamento de float.

Auditoria: Relatório detalhado de itens encontrados, compatibilidade (%) e divergências.

Exportação Profissional: Geração automática de relatórios de auditoria em PDF.

Segurança de Dados: Arquitetura baseada em memória (processamento em RAM); nenhum dado sensível é armazenado permanentemente no servidor.

🛠️ Tecnologias Utilizadas
Python 3.x

Streamlit: Interface web responsiva e ágil.

Pandas: Manipulação e tratamento de dados tabulares.

Pdfplumber: Engine de leitura e extração de tabelas de PDFs.

ReportLab: Geração de documentos PDF profissionais.

RapidFuzz: Motor de comparação inteligente de strings.

📋 Como Configurar e Rodar
1. Pré-requisitos
Certifique-se de ter o Python instalado. Clone este repositório e, no seu terminal, instale as dependências:

Bash
pip install -r requirements.txt
(Caso não tenha o arquivo requirements.txt, instale manualmente: pip install streamlit pandas pdfplumber rapidfuzz reportlab openpyxl)

2. Execução
Para rodar a aplicação localmente:

Bash
streamlit run PoupaMed.py
💡 Manual de Uso para Homologação
Passo 1 (Lista de Desejos): Suba o arquivo contendo a demanda do hospital (aceita .xlsx, .csv ou .txt). O sistema busca automaticamente pelas colunas "Produto" e "Quantidade".

Passo 2 (Fornecedores): Suba uma ou várias cotações dos fornecedores. O sistema processa PDFs, planilhas e arquivos texto simultaneamente.

Auditoria: Utilize o "Modo Debug" ativado na barra lateral para ver exatamente como o sistema está fatiando seus PDFs.

Ranking: O sistema apresentará o fornecedor com melhor custo-benefício, respeitando o critério de Maior Compatibilidade (Score) > Menor Preço.

🔒 Segurança e Privacidade
O sistema opera em modo de processamento volátil. Os arquivos enviados são lidos na memória RAM e descartados imediatamente após o fechamento da sessão do usuário. Não realizamos persistência de dados sensíveis de pacientes ou propostas comerciais.