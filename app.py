import streamlit as st
from PIL import Image
import requests
import pandas as pd
import io
import altair as alt

# Inicializando o dicionário de votos acumulados e lista de imagens de QR Codes no session_state
if 'voto_acumulado' not in st.session_state:
    st.session_state.voto_acumulado = {'Prefeito': {}, 'Vereador': {}}
if 'total_votos' not in st.session_state:
    st.session_state.total_votos = 0
if 'qrcode_images' not in st.session_state:
    st.session_state.qrcode_images = []  # Armazena (imagem, erro_detectado, votos_do_qrcode)
if 'last_uploaded_file' not in st.session_state:
    st.session_state.last_uploaded_file = None

def main():
    st.title("Leitor de QRCode - Boletim de Urna Eletrônica")

    # Filtro de quantidade de candidatos para exibição
    max_candidatos = st.slider("Selecione quantos candidatos deseja visualizar:", min_value=5, max_value=20, value=15)

    # Carregar uma imagem com QR Code
    run_image_upload(max_candidatos)

# Função para upload de uma única imagem contendo o QR Code
def run_image_upload(max_candidatos):
    uploaded_file = st.file_uploader("Envie uma imagem com QR Code", type=["jpg", "jpeg", "png"])

    # Verifica se foi feito um novo upload
    if uploaded_file is not None and uploaded_file != st.session_state.last_uploaded_file:
        # Abrir a imagem carregada
        image = Image.open(uploaded_file)
        
        # Converter a imagem para o formato PNG para enviar à API
        image.save("temp_image.png", "PNG")

        # Enviar a imagem para a API zxing e decodificar o QR Code
        qr_data = decode_qr_code("temp_image.png")

        if qr_data:
            st.success("QR Code detectado:")
            data_dict = display_qr_data(qr_data)
            erro_detectado = False

            if data_dict:
                # Armazenar os votos desse QR Code específico
                votos_do_qrcode = {'Prefeito': {}, 'Vereador': {}, 'Branco': 0, 'Nulo': 0}
                
                # Acumular votos dos candidatos, separando Prefeito (2 dígitos) e Vereador (5 dígitos)
                for candidato, votos in data_dict.items():
                    if candidato.startswith("Candidato"):
                        numero_candidato = candidato.split(" ")[1]
                        votos = int(votos)
                        
                        if len(numero_candidato) == 2:  # Prefeito
                            if candidato not in st.session_state.voto_acumulado['Prefeito']:
                                st.session_state.voto_acumulado['Prefeito'][candidato] = 0
                            st.session_state.voto_acumulado['Prefeito'][candidato] += votos
                            votos_do_qrcode['Prefeito'][candidato] = votos
                        elif len(numero_candidato) == 5:  # Vereador
                            if candidato not in st.session_state.voto_acumulado['Vereador']:
                                st.session_state.voto_acumulado['Vereador'][candidato] = 0
                            st.session_state.voto_acumulado['Vereador'][candidato] += votos
                            votos_do_qrcode['Vereador'][candidato] = votos

                        st.session_state.total_votos += votos

                    elif candidato in ["BRAN", "NULO"]:  # Armazenar Brancos e Nulos
                        votos_do_qrcode[candidato] = int(votos)

        else:
            st.warning("Nenhum QR Code detectado na imagem.")
            erro_detectado = True
            votos_do_qrcode = {}

        # Armazenar a imagem, se houve erro e os votos desse QR Code
        st.session_state.qrcode_images.append((image, erro_detectado, votos_do_qrcode))

        # Salvar o último arquivo enviado no estado para não processar o mesmo upload repetidamente
        st.session_state.last_uploaded_file = uploaded_file

    # Exibir os QR Codes com borda vermelha para os que deram erro
    mostrar_qrcodes()

    # Mostrar o gráfico geral separado por Prefeito e Vereador
    gerar_grafico_geral()

    # Mostrar o ranking atualizado para Prefeito e Vereador, mesmo que haja erro
    ranking_prefeito_df, ranking_vereador_df = mostrar_ranking(max_candidatos)
    
    # Gerar gráficos de barras para Prefeito e Vereador
    gerar_graficos_qrcodes(ranking_prefeito_df, 'Prefeito')
    gerar_graficos_qrcodes(ranking_vereador_df, 'Vereador')

    # Gerar Excel para download
    generate_excel(st.session_state.voto_acumulado)

# Função para exibir todos os QR Codes, com borda vermelha nos que falharam
def mostrar_qrcodes():
    if st.session_state.qrcode_images:
        st.write("### QR Codes")
        colunas = st.columns(len(st.session_state.qrcode_images))
        for idx, (img, erro, votos_do_qrcode) in enumerate(st.session_state.qrcode_images):
            with colunas[idx]:
                if erro:
                    st.image(img, caption=f"QR Code {idx + 1} - Erro", use_column_width=False, width=150)
                    st.markdown(f'<div style="border: 2px solid red; padding: 5px; text-align: center;">QR Code {idx + 1}</div>', unsafe_allow_html=True)
                else:
                    st.image(img, caption=f"QR Code {idx + 1}", use_column_width=False, width=150)
                
                # Garantir que a chave do botão seja única usando o índice e o timestamp da imagem
                if st.button(f"Remover QR Code {idx + 1}", key=f"remove_{idx}_{img}"):
                    # Remover os votos associados a esse QR Code
                    for categoria, votos in votos_do_qrcode.items():
                        if categoria in ["Prefeito", "Vereador"]:
                            for candidato, votos in votos.items():
                                st.session_state.voto_acumulado[categoria][candidato] -= votos
                                st.session_state.total_votos -= votos

                    # Remover o QR Code da lista
                    st.session_state.qrcode_images.pop(idx)

                    # Forçar a re-renderização da interface
                    st.session_state.last_uploaded_file = None
                    break  # Forçar o fim do loop para evitar conflitos ao atualizar a lista

                    # Mostrar a tabela e os QR Codes restantes
                    mostrar_qrcodes()
                    mostrar_ranking()

# Função para enviar a imagem para a API zxing e decodificar
def decode_qr_code(image_path):
    url = 'http://api.qrserver.com/v1/read-qr-code/'
    with open(image_path, 'rb') as f:
        files = {'file': f}
        response = requests.post(url, files=files)
    
    if response.status_code == 200:
        json_data = response.json()
        try:
            # Extrair a informação do QR Code
            qr_data = json_data[0]['symbol'][0]['data']
            return qr_data
        except Exception as e:
            st.error(f"Erro ao decodificar o QR Code: {e}")
            return None
    else:
        st.error(f"Erro ao acessar a API: {response.status_code}")
        return None

# Função para exibir os dados do QRCode de forma organizada
def display_qr_data(qr_data):
    data_dict = parse_qr_data(qr_data)
    return data_dict

# Função para organizar os dados do QR Code
def parse_qr_data(qr_data):
    data_dict = {}
    qr_info_list = qr_data.split(" ")

    # Itera sobre a string e identifica os votos dos candidatos (ex: "12:21", "13:30", etc)
    for info in qr_info_list:
        if ":" in info:
            key_value = info.split(":")
            if len(key_value) == 2:
                candidato, votos = key_value
                if candidato.isdigit() or candidato in ["BRAN", "NULO"]:  # Incluindo Brancos e Nulos
                    data_dict[f"Candidato {candidato}" if candidato.isdigit() else candidato] = votos

    return data_dict

# Função para mostrar o ranking dos candidatos com base no filtro
def mostrar_ranking(max_candidatos):
    st.write(f"### Ranking dos Candidatos a Prefeito (Top {max_candidatos})")
    ranking_prefeito_df = pd.DataFrame(list(st.session_state.voto_acumulado['Prefeito'].items()), columns=["Candidato", "Votos"])
    ranking_prefeito_df = ranking_prefeito_df[ranking_prefeito_df["Votos"] > 0]  # Filtra candidatos com votos
    ranking_prefeito_df = ranking_prefeito_df.sort_values(by="Votos", ascending=False).head(max_candidatos)  # Ordenar por votos e limitar pela quantidade escolhida
    ranking_prefeito_df = ranking_prefeito_df.reset_index(drop=True)
    ranking_prefeito_df.index += 1  # Faz a indexação começar em 1
    st.table(ranking_prefeito_df)

    st.write(f"### Ranking dos Candidatos a Vereador (Top {max_candidatos})")
    ranking_vereador_df = pd.DataFrame(list(st.session_state.voto_acumulado['Vereador'].items()), columns=["Candidato", "Votos"])
    ranking_vereador_df = ranking_vereador_df[ranking_vereador_df["Votos"] > 0]  # Filtra candidatos com votos
    ranking_vereador_df = ranking_vereador_df.sort_values(by="Votos", ascending=False).head(max_candidatos)  # Ordenar por votos e limitar pela quantidade escolhida
    ranking_vereador_df = ranking_vereador_df.reset_index(drop=True)
    ranking_vereador_df.index += 1  # Faz a indexação começar em 1
    st.table(ranking_vereador_df)

    return ranking_prefeito_df, ranking_vereador_df

# Função para gerar o gráfico de barras geral separado por Prefeito e Vereador
def gerar_grafico_geral():
    st.write("### Gráfico Geral de Votos - Prefeito e Vereador")
    
    col1, col2 = st.columns(2)

    # Gráfico de Prefeito
    with col1:
        st.write("#### Prefeito")
        if st.session_state.voto_acumulado['Prefeito']:
            gerar_grafico_por_cargo('Prefeito', st.session_state.voto_acumulado['Prefeito'])
        else:
            st.write("Nenhum voto registrado para Prefeito.")

    # Gráfico de Vereador
    with col2:
        st.write("#### Vereador")
        if st.session_state.voto_acumulado['Vereador']:
            gerar_grafico_por_cargo('Vereador', st.session_state.voto_acumulado['Vereador'])
        else:
            st.write("Nenhum voto registrado para Vereador.")

# Função para gerar gráficos de barras com Altair para cada cargo
def gerar_grafico_por_cargo(cargo, votos_cargo):
    # Criar DataFrame
    chart_data = pd.DataFrame(list(votos_cargo.items()), columns=["Candidato", "Votos"])
    chart_data = chart_data[chart_data["Votos"] > 0].sort_values(by="Votos", ascending=False)

    # Criar o gráfico com Altair
    chart = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X('Candidato', sort='-y'),
        y='Votos',
        tooltip=['Candidato', 'Votos']
    ).interactive()

    # Exibir o gráfico
    st.altair_chart(chart, use_container_width=True)

# Função para gerar gráficos de barras com Altair para cada QR Code com valores no topo das barras
def gerar_graficos_qrcodes(ranking_df, cargo):
    st.write(f"### Gráficos de Votos para {cargo} (Top Candidatos)")
    for idx, (_, erro, votos_do_qrcode) in enumerate(st.session_state.qrcode_images):
        if not erro and votos_do_qrcode[cargo]:
            # Gerar os dados do gráfico com base na mesma ordem da tabela
            candidatos = ranking_df["Candidato"].values
            votos = [votos_do_qrcode[cargo].get(candidato, 0) for candidato in candidatos]
            
            # Criar DataFrame para Altair
            chart_data = pd.DataFrame({
                'Candidato': candidatos,
                'Votos': votos
            })
            
            # Criar o gráfico com Altair
            chart = alt.Chart(chart_data).mark_bar().encode(
                x=alt.X('Candidato', sort='-y'),
                y='Votos',
                tooltip=['Candidato', 'Votos']
            ).properties(
                title=f"Gráfico de Votos - {cargo} - Sessão {idx + 1}"
            ).interactive()
            
            # Exibir o gráfico
            st.altair_chart(chart, use_container_width=True)

            # Exibir a quantidade de votos em Branco e Nulo abaixo do gráfico
            brancos = votos_do_qrcode.get("BRAN", 0)
            nulos = votos_do_qrcode.get("NULO", 0)
            st.write(f"**Brancos**: {brancos} | **Nulos**: {nulos}")

# Função para gerar a planilha Excel e disponibilizar para download
def generate_excel(voto_acumulado):
    urna_prefeito_df = pd.DataFrame(list(voto_acumulado['Prefeito'].items()), columns=["Candidato", "Votos"])
    urna_vereador_df = pd.DataFrame(list(voto_acumulado['Vereador'].items()), columns=["Candidato", "Votos"])

    # Criar um buffer em memória para armazenar o arquivo Excel
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')

    # Escrever os DataFrames no escritor Excel
    urna_prefeito_df.to_excel(writer, index=False, sheet_name='Prefeito')
    urna_vereador_df.to_excel(writer, index=False, sheet_name='Vereador')

    # Fechar o escritor para garantir que todos os dados foram gravados no buffer
    writer.close()

    # Obter o conteúdo do buffer
    processed_data = output.getvalue()

    # Botão para download do Excel
    st.download_button(
        label="Baixar planilha com os dados",
        data=processed_data,
        file_name="resultados_votacao.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

if __name__ == '__main__': 
    main()
