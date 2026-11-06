import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import re
from datetime import datetime

# Configuração da página
st.set_page_config(page_title="Painel de Análises CDV e TJ", layout="wide")

st.title("📊 Painel de Análises CDV e TJ")

# --- BARRA LATERAL: MENU E UPLOAD ---
st.sidebar.header("📁 Importação e Configurações")

# 1. Menu de Navegação
modo_analise = st.sidebar.radio(
    "Selecione o tipo de análise:",
    ["Falsa Ocupação", "Teste de Junta (TJ)"]
)

st.sidebar.markdown("---")

# 2. Upload do Arquivo (Único para ambas as análises)
uploaded_file = st.sidebar.file_uploader("Faça upload do arquivo CSV/TSV", type=["csv", "txt"])

if uploaded_file is not None:
    try:
        # Carregamento e padronização (usando o separador \t como padrão do primeiro script)
        df = pd.read_csv(
            uploaded_file,
            sep='\t',
            engine='python',
            on_bad_lines='skip',
            encoding='latin1',
            header=0
        )

        df.columns = df.columns.str.strip()

        # Unificando os nomes das colunas para evitar conflitos entre os scripts
        if 'Origem_CDV' in df.columns:
            df = df.rename(columns={'Origem_CDV': 'Origem'})
        if 'Descricao' in df.columns:
            df = df.rename(columns={'Descricao': 'Descrição'})

        # Limpeza de espaços
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = df[col].str.strip()

        df = df.dropna(subset=['Data/Hora', 'Origem', 'Descrição'], how='any').copy()
        
        # Conversão de Data/Hora
        df['Data/Hora_dt'] = pd.to_datetime(df['Data/Hora'], format='%d/%m/%Y %H:%M:%S.%f', errors='coerce')
        df = df.dropna(subset=['Data/Hora_dt']).copy()

        # Filtros de data e hora compartilhados
        min_date = df['Data/Hora_dt'].dt.date.min()
        max_date = df['Data/Hora_dt'].dt.date.max()

        st.sidebar.subheader("Filtros de Tempo")
        data_selecionada = st.sidebar.date_input("Data da Análise", value=min_date, min_value=min_date, max_value=max_date)
        hora_inicio, hora_fim = st.sidebar.slider("Intervalo de Horas", 0, 23, (6, 22))
        
        # Filtro de Delta de tempo dinâmico dependendo da análise escolhida
        if modo_analise == "Falsa Ocupação":
            delta_maximo = st.sidebar.number_input("Delta Máximo (segundos)", min_value=1, max_value=60, value=10)
        else:
            delta_maximo = st.sidebar.number_input("Delta Máximo (segundos)", min_value=1, max_value=60, value=30)

        # Aplica o filtro de tempo
        df_filtrado = df[
            (df['Data/Hora_dt'].dt.date == data_selecionada) &
            (df['Data/Hora_dt'].dt.hour >= hora_inicio) &
            (df['Data/Hora_dt'].dt.hour <= hora_fim)
        ].copy()

        st.info(f"Modo Ativo: **{modo_analise}** | Registros carregados: **{len(df_filtrado)}**")

        if not df_filtrado.empty:
            df_filtrado = df_filtrado.sort_values(by=['Origem', 'Data/Hora_dt']).reset_index(drop=True)

            # ==========================================
            # MODO 1: FALSA OCUPAÇÃO
            # ==========================================
            if modo_analise == "Falsa Ocupação":
                casos_detectados = []

                for cdv, grupo in df_filtrado.groupby('Origem'):
                    grupo = grupo.reset_index(drop=True)

                    for i in range(len(grupo) - 1):
                        linha_atual = grupo.iloc[i]
                        proxima_linha = grupo.iloc[i+1]

                        desc_atual = str(linha_atual['Descrição'])
                        desc_prox = str(proxima_linha['Descrição'])

                        texto_livre = f"IND: Bloco do CDV {cdv} livre"
                        texto_ocupado = f"IND: Bloco do CDV {cdv} ocupado"

                        condicao_a = (texto_ocupado in desc_atual) and (texto_livre in desc_prox)
                        condicao_b = (texto_livre in desc_atual) and (texto_ocupado in desc_prox)

                        if condicao_a or condicao_b:
                            delta_tempo = (proxima_linha['Data/Hora_dt'] - linha_atual['Data/Hora_dt']).total_seconds()

                            if abs(delta_tempo) <= delta_maximo:
                                casos_detectados.append({
                                    'Origem (CDV)': cdv,
                                    'Hora do Primeiro Registro': linha_atual['Data/Hora'],
                                    'Hora do segundo Registro': proxima_linha['Data/Hora'],
                                    'Delta de Tempo (s)': delta_tempo
                                })

                df_resultado = pd.DataFrame(casos_detectados)

                if not df_resultado.empty:
                    st.success(f"**{len(df_resultado)}** falsas ocupações detectadas!")
                    
                    st.download_button(
                        label="📥 Baixar Consolidação (.CSV)",
                        data=df_resultado.to_csv(index=False).encode('utf-8'),
                        file_name=f"falsa_ocupacao_{data_selecionada.strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )

                    def gerar_grafico_dominio(df_dados, prefixo, titulo, cor_paleta):
                        df_dominio = df_dados[df_dados['Origem (CDV)'].str.startswith(prefixo, na=False)].copy()

                        if df_dominio.empty:
                            st.warning(f"Nenhuma ocorrência para **{prefixo}**.")
                            return

                        df_dominio['CDV_Base'] = df_dominio['Origem (CDV)'].apply(lambda x: re.sub(r'-(R|C|N)$', '', x.strip()))
                        if prefixo == 'PSG':
                            df_dominio['CDV_Base'] = df_dominio['CDV_Base'].apply(lambda x: re.sub(r'(PSG T\d+D)\s*(\d+)', r'\1', x))
                        df_dominio = df_dominio.drop_duplicates(subset=['CDV_Base', 'Hora do Primeiro Registro'], keep='first')

                        frequencia = df_dominio['CDV_Base'].value_counts().reset_index()
                        frequencia.columns = ['Origem (CDV)', 'Frequência']

                        fig, ax = plt.subplots(figsize=(10, 4))
                        sns.set_theme(style="whitegrid")
                        grafico = sns.barplot(x='Origem (CDV)', y='Frequência', data=frequencia, palette=cor_paleta, hue='Origem (CDV)', legend=False, ax=ax)
                        
                        data_formatada = data_selecionada.strftime('%d/%m/%Y')
                        ax.set_title(f'Frequência de Oscilações (<={delta_maximo}s) {titulo} - {data_formatada}', fontsize=11, fontweight='bold', pad=15)                        
                        ax.tick_params(axis='x', rotation=45)
                        
                        for p in grafico.patches:
                            height = p.get_height()
                            if height > 0:
                                grafico.annotate(format(height, '.0f'), (p.get_x() + p.get_width() / 2., height), ha='center', va='center', xytext=(0, 8), textcoords='offset points', fontsize=9, fontweight='bold')
                        plt.tight_layout()
                        st.pyplot(fig)
                        plt.close(fig)

                    st.markdown("---")
                    aba1, aba2, aba3, aba4 = st.tabs(["SAI", "MSH", "VRO", "PSG"])
                    with aba1: gerar_grafico_dominio(df_resultado, 'SAI', 'Domínio SAI', 'viridis')
                    with aba2: gerar_grafico_dominio(df_resultado, 'MSH', 'Domínio MSH', 'magma')
                    with aba3: gerar_grafico_dominio(df_resultado, 'VRO', 'Domínio VRO', 'crest')
                    with aba4: gerar_grafico_dominio(df_resultado, 'PSG', 'Domínio PSG', 'plasma')
                else:
                    st.warning("Nenhum registro atendeu aos critérios de Falsa Ocupação.")

            # ==========================================
            # MODO 2: TESTE DE JUNTA (TJ)
            # ==========================================
            elif modo_analise == "Teste de Junta (TJ)":
                casos_tj = []

                for cdv, grupo in df_filtrado.groupby('Origem'):
                    if "T1AD" in str(cdv) or "T1BD" in str(cdv):
                        continue

                    grupo = grupo.reset_index(drop=True)

                    for i in range(len(grupo) - 1):
                        linha_atual = grupo.iloc[i]
                        proxima_linha = grupo.iloc[i+1]

                        desc_atual = str(linha_atual['Descrição'])
                        desc_prox = str(proxima_linha['Descrição'])

                        texto_base_cdv = f"IND: BPoint {cdv}"
                        atual_valido = (texto_base_cdv in desc_atual) and ("TJ" in desc_atual)
                        prox_valido = (texto_base_cdv in desc_prox) and ("TJ" in desc_prox)

                        if atual_valido and prox_valido:
                            delta_tempo = (proxima_linha['Data/Hora_dt'] - linha_atual['Data/Hora_dt']).total_seconds()

                            if abs(delta_tempo) <= delta_maximo:
                                casos_tj.append({
                                    'Origem (CDV)': cdv,
                                    'Hora do Primeiro Registro': linha_atual['Data/Hora'],
                                    'Delta (s)': delta_tempo
                                })

                df_resultado_tj = pd.DataFrame(casos_tj)

                if not df_resultado_tj.empty:
                    st.success(f"**{len(df_resultado_tj)}** casos de TJ detectados!")
                    
                    st.download_button(
                        label="📥 Baixar Casos TJ (.CSV)",
                        data=df_resultado_tj.to_csv(index=False).encode('utf-8'),
                        file_name=f"teste_junta_{data_selecionada.strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )

                    # Tabela de Frequência e Gráfico
                    frequencia_tj = df_resultado_tj['Origem (CDV)'].value_counts().reset_index()
                    frequencia_tj.columns = ['Origem (CDV)', 'Frequência']
                    frequencia_tj['Dominio'] = frequencia_tj['Origem (CDV)'].apply(lambda x: str(x).split(' ')[0])

                    st.markdown("---")
                    st.subheader("Gráfico Geral de Teste de Junta")
                    
                    fig, ax = plt.subplots(figsize=(12, 6))
                    sns.set_theme(style="whitegrid")
                    
                    grafico = sns.barplot(
                        x='Origem (CDV)', y='Frequência', hue='Dominio', 
                        data=frequencia_tj, palette='viridis', dodge=False, ax=ax
                    )

                    ax.set_title(f'Frequência de Oscilações por TJ (<={delta_maximo}s) - {data_selecionada.strftime("%d/%m/%Y")}', fontsize=14, fontweight='bold', pad=15)
                    ax.set_xlabel('Nome do CDV (Origem)', fontsize=12)
                    ax.set_ylabel('Quantidade de Vezes', fontsize=12)
                    plt.xticks(rotation=45, ha='right')

                    for p in grafico.patches:
                        height = p.get_height()
                        if height > 0:
                            grafico.annotate(format(height, '.0f'), (p.get_x() + p.get_width() / 2., height), ha='center', va='center', xytext=(0, 9), textcoords='offset points', fontsize=10, fontweight='bold')

                    plt.tight_layout()
                    st.pyplot(fig)
                    plt.close(fig)
                else:
                    st.warning("Nenhum registro atendeu aos critérios de Teste de Junta (TJ).")

        else:
            st.warning("Nenhum dado retornado para a data e faixa de horário selecionadas.")

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")
else:
    st.info("👈 Faça o upload de um arquivo CSV/TSV na barra lateral para iniciar.")
