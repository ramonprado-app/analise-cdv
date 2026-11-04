import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import re
from datetime import datetime

# Configuração da página para modo tela cheia
st.set_page_config(page_title="Análise de Oscilações de CDV", layout="wide")

st.title("📊 Análise de Oscilações de CDV")

# --- BARRA LATERAL: CONTROLES E FILTROS ---
st.sidebar.header("📁 Importação e Filtros")

# 1. Upload do Arquivo CSV
uploaded_file = st.sidebar.file_uploader("Faça upload do arquivo CSV/TSV", type=["csv", "txt"])

if uploaded_file is not None:
    try:
        # Carrega o CSV usando o arquivo vindo do upload do usuário
        df = pd.read_csv(
            uploaded_file,
            sep='\t',
            engine='python',
            on_bad_lines='skip',
            encoding='latin1',
            header=0
        )

        df.columns = df.columns.str.strip()

        # Limpeza de espaços nos textos
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = df[col].str.strip()

        df = df.dropna(subset=['Data/Hora', 'Origem', 'Descrição'], how='any').copy()
        
        # Conversão de Data/Hora
        df['Data/Hora_dt'] = pd.to_datetime(df['Data/Hora'], format='%d/%m/%Y %H:%M:%S.%f', errors='coerce')
        df = df.dropna(subset=['Data/Hora_dt']).copy()

        # Extrai os limites de datas disponíveis no arquivo para configurar os seletores
        min_date = df['Data/Hora_dt'].dt.date.min()
        max_date = df['Data/Hora_dt'].dt.date.max()

        # Seletores dinâmicos na interface
        st.sidebar.subheader("Parâmetros da Análise")
        data_selecionada = st.sidebar.date_input("Data da Análise", value=min_date, min_value=min_date, max_value=max_date)
        hora_inicio, hora_fim = st.sidebar.slider("Intervalo de Horas", 0, 23, (6, 22))
        delta_maximo = st.sidebar.number_input("Delta Máximo de Tempo (segundos)", min_value=1, max_value=60, value=10)

        # 2. Filtragem dos Dados
        df_filtrado = df[
            (df['Data/Hora_dt'].dt.date == data_selecionada) &
            (df['Data/Hora_dt'].dt.hour >= hora_inicio) &
            (df['Data/Hora_dt'].dt.hour <= hora_fim)
        ].copy()

        st.info(f"Registros encontrados na faixa selecionada ({data_selecionada.strftime('%d/%m/%Y')} das {hora_inicio}h às {hora_fim}h): **{len(df_filtrado)}**")

        if not df_filtrado.empty:
            df_filtrado = df_filtrado.sort_values(by=['Origem', 'Data/Hora_dt']).reset_index(drop=True)

            casos_detectados = []

            # 3. Algoritmo de Varredura por CDV
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
                st.success(f"**{len(df_resultado)}** oscilações detectadas!")

                # Botão para baixar a planilha consolidada
                st.download_button(
                    label="📥 Baixar Casos Consolidados (.CSV)",
                    data=df_resultado.to_csv(index=False).encode('utf-8'),
                    file_name=f"casos_consolidados_{data_selecionada.strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )

                # 4. Função Interna de Geração de Gráficos
                def gerar_grafico_dominio(df_dados, prefixo, titulo, cor_paleta):
                    df_dominio = df_dados[df_dados['Origem (CDV)'].str.startswith(prefixo, na=False)].copy()

                    if df_dominio.empty:
                        st.warning(f"Nenhuma ocorrência encontrada para o domínio **{prefixo}**.")
                        return

                    # Limpeza de sufixos (-R, -C, -N)
                    df_dominio['CDV_Base'] = df_dominio['Origem (CDV)'].apply(lambda x: re.sub(r'-(R|C|N)$', '', x.strip()))

                    # Tratamento específico PSG
                    if prefixo == 'PSG':
                        df_dominio['CDV_Base'] = df_dominio['CDV_Base'].apply(
                            lambda x: re.sub(r'(PSG T\d+D)\s*(\d+)', r'\1', x)
                        )

                    df_dominio = df_dominio.drop_duplicates(subset=['CDV_Base', 'Hora do Primeiro Registro'], keep='first')

                    frequencia = df_dominio['CDV_Base'].value_counts().reset_index()
                    frequencia.columns = ['Origem (CDV)', 'Frequência']

                    # Agrupamento de Outros (<5)
                    maiores_que_5 = frequencia[frequencia['Frequência'] >= 5]
                    menores_que_5 = frequencia[frequencia['Frequência'] < 5]

                    if not menores_que_5.empty:
                        total_outros = menores_que_5['Frequência'].sum()
                        linha_outros = pd.DataFrame([{'Origem (CDV)': 'Outros (<5)', 'Frequência': total_outros}])
                        frequencia_grafico = pd.concat([maiores_que_5, linha_outros], ignore_index=True)
                    else:
                        frequencia_grafico = frequencia

                    # Plotagem
                    fig, ax = plt.subplots(figsize=(10, 4))
                    sns.set_theme(style="whitegrid")

                    grafico = sns.barplot(
                        x='Origem (CDV)',
                        y='Frequência',
                        data=frequencia_grafico,
                        palette=cor_paleta,
                        hue='Origem (CDV)',
                        legend=False,
                        ax=ax
                    )

                    ax.set_title(f'Frequência de Oscilações (<={delta_maximo}s) {data_selecionada.strftime("%d/%m/%Y")} - {hora_inicio}h às {hora_fim}h - {titulo}', fontsize=11, fontweight='bold', pad=15)
                    ax.set_xlabel('Nome do CDV', fontsize=10)
                    ax.set_ylabel('Frequência (Ocorrências)', fontsize=10)
                    ax.tick_params(axis='x', rotation=45)

                    for p in grafico.patches:
                        height = p.get_height()
                        if height > 0:
                            grafico.annotate(format(height, '.0f'),
                                             (p.get_x() + p.get_width() / 2., height),
                                             ha='center', va='center',
                                             xytext=(0, 8), textcoords='offset points', fontsize=9, fontweight='bold')

                    plt.tight_layout()
                    st.pyplot(fig)
                    plt.close(fig)

                # 5. Exibição dos Gráficos em Abas
                st.markdown("---")
                st.subheader("Gráficos de Frequência por Domínio")

                aba1, aba2, aba3, aba4 = st.tabs(["Domínio SAI", "Domínio MSH", "Domínio VRO", "Domínio PSG"])

                with aba1:
                    gerar_grafico_dominio(df_resultado, 'SAI', 'Domínio SAI', 'viridis')
                with aba2:
                    gerar_grafico_dominio(df_resultado, 'MSH', 'Domínio MSH', 'magma')
                with aba3:
                    gerar_grafico_dominio(df_resultado, 'VRO', 'Domínio VRO', 'crest')
                with aba4:
                    gerar_grafico_dominio(df_resultado, 'PSG', 'Domínio PSG', 'plasma')

            else:
                st.warning(f"Nenhum registro atendeu ao critério de delta <= {delta_maximo}s no intervalo selecionado.")
        else:
            st.warning("Nenhum dado retornado para a data e faixa de horário selecionadas.")

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")
else:
    st.info("👈 Faça o upload de um arquivo CSV/TSV na barra lateral para iniciar.")