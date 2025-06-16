from flask import Flask, render_template, request, redirect, session, url_for
import psycopg2
import psycopg2.extras
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'chave-padrao-fraca')

def conectar_banco():
    try:
        # DATABASE_URL:
        # host=host user=user password=password dbname=database port=5432
        conn_str = os.getenv('DATABASE_URL')
        conexao = psycopg2.connect(conn_str)
        return conexao
    except Exception as e:
        print("Erro ao conectar:", e)
        return None

@app.route('/', methods=['GET', 'POST'])
def login():
    mensagem = ''
    if request.method == 'POST':
        id_motorista = request.form['id_motorista']
        senha = request.form['cpf']

        conexao = conectar_banco()
        if conexao:
            cursor = conexao.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM Motoristas WHERE id_motorista = %s AND CPF = %s", (id_motorista, senha))
            motorista = cursor.fetchone()
            cursor.close()
            conexao.close()

            if motorista:
                session['id_motorista'] = id_motorista

                # Verifica se o ID é de supervisor
                if id_motorista.upper() in ['001', '002']:
                    return redirect(url_for('painel_supervisor'))
                else:
                    return redirect(url_for('painel'))

            else:
                mensagem = 'ID ou Senha incorretos.'

    return render_template('login.html', mensagem=mensagem)


def calcular_media(lista, chave, ignora_percentual=False):
    valores = []
    for item in lista:
        valor = item[chave]
        if valor in (None, "-", "", "NULL"):
            continue
        if ignora_percentual:
            valor = str(valor).replace("%", "").strip().replace(",", ".")
        try:
            valor_float = float(valor)
            valores.append(valor_float)
        except ValueError:
            continue
    if not valores:
        return "-"
    media = sum(valores) / len(valores)
    return round(media, 2)


from flask import request

@app.route('/painel')
def painel():
    if 'id_motorista' not in session:
        return redirect(url_for('login'))

    id_motorista = session['id_motorista']
    mes_selecionado = request.args.get('mes', '')

    conexao = conectar_banco()
    dados_formatados = []
    observacoes = []
    prontuario = ""
    resultados = []

    if conexao:
        cursor = None
        try:
            cursor = conexao.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            query = """
                    SELECT 
                        TO_CHAR(D.data, 'YYYY-MM-DD') AS dataiso, 
                        D.devolucao_porcentagem, 
                        COALESCE(NULLIF(S.dispersao_km, '')::numeric, 0) AS dispersao_km,
                        R.Rating,
                        COALESCE(NULLIF(P.reposicao_valor, '')::numeric, 0) AS reposicao_valor,
                        COALESCE(NULLIF(F.refugo_porcentagem, '')::numeric, 0) AS refugo_porcentagem
                    FROM devolucao D
                    LEFT JOIN dispersao S ON D.id_motorista = S.id_motorista AND D.data = S.data
                    LEFT JOIN Rating R ON D.id_motorista = R.id_motorista AND D.data = R.data
                    LEFT JOIN Reposicao P ON D.id_motorista = P.id_motorista AND D.data = P.data
                    LEFT JOIN Refugo F ON D.id_motorista = F.id_motorista AND D.data = F.data
                    WHERE D.id_motorista = %s

            """
            params = [id_motorista]
            if mes_selecionado:
                query += " AND TO_CHAR(D.data, 'YYYY-MM') = %s"
                params.append(mes_selecionado)

            query += " ORDER BY D.data ASC"

            cursor.execute(query, tuple(params))
            resultados = cursor.fetchall()

            for linha in resultados:
                data = linha.get('dataiso')
                if data:
                    partes = data.split('-')
                    data_formatada = f"{partes[2]}-{partes[1]}-{partes[0]}"
                else:
                    data_formatada = "-"

                devolucao_raw = linha.get('devolucao_porcentagem')

                if devolucao_raw in (None, "NULL", "", "-"):
                    devolucao_porcentagem_valor = "-"
                    dispersao = "-"
                    reposicao = "-"
                    refugo = "-"
                else:
                    devolucao_porcentagem_valor = str(devolucao_raw).replace("%", "").strip()
                    dispersao = linha.get('dispersao_km')
                    reposicao = linha.get('reposicao_valor')
                    refugo = linha.get('refugo_porcentagem')
                    
                    dispersao = "-" if dispersao in (None, "NULL") else float(dispersao)
                    reposicao = "-" if reposicao in (None, "NULL") else str(reposicao).replace('.', ',')
                    refugo = "-" if refugo in (None, "NULL") else float(refugo)
                    
                rating = linha.get('rating')
                rating = "-" if rating in (None, "NULL", "") else rating
                rating = rating.replace(',00', '') if isinstance(rating, str) else rating

                dados_formatados.append({
                    'data': data_formatada,
                    'devolucao_porcentagem': devolucao_porcentagem_valor,
                    'dispersao_km': dispersao,
                    'rating': rating,
                    'reposicao_valor': reposicao,
                    'refugo_porcentagem': refugo
                })

            cursor.execute("SELECT Texto FROM Observacoes WHERE id_motorista = %s", (id_motorista,))
            observacoes = [linha.get('texto', '') for linha in cursor.fetchall()]

            cursor.execute("SELECT Prontuario FROM Telemetria WHERE id_motorista = %s", (id_motorista,))
            resultado_prontuario = cursor.fetchone()
            prontuario = resultado_prontuario.get('prontuario', "") if resultado_prontuario else ""

        except Exception as e:
            print("Erro ao consultar o banco:", e)
        finally:
            if cursor:
                cursor.close()
            conexao.close()


    media_devolucao_porcentagem = calcular_media(dados_formatados, 'devolucao_porcentagem', ignora_percentual=True)
    media_dispersao_km = calcular_media(dados_formatados, 'dispersao_km', ignora_percentual=True)
    media_rating = calcular_media(dados_formatados, 'rating')
    soma_reposicao = sum(
        float(item['reposicao_valor'].replace(',', '.')) 
        for item in dados_formatados 
        if item['reposicao_valor'] not in (None, '', 'N/A', '-')
    )
    media_refugo = calcular_media(dados_formatados, 'refugo_porcentagem', ignora_percentual=True)

    return render_template('painel.html', dados=dados_formatados, observacoes=observacoes,
                           medias={
                               'devolucao_porcentagem': media_devolucao_porcentagem,
                               'dispersao_km': media_dispersao_km,
                               'rating': media_rating,
                               'reposicao_valor': f"{soma_reposicao:.2f}".replace('.', ','),
                               'refugo_porcentagem': media_refugo
                           },
                           prontuario=prontuario,
                           mes_atual=mes_selecionado or "")



@app.route('/painel_supervisor', methods=['GET', 'POST'])
def painel_supervisor():
    conexao = conectar_banco()
    funcionarios = []
    dados_formatados = []
    indicadores = None
    mensagem = ''
    filtro_mes = None
    id_selecionado = None

    if conexao:
        cursor = conexao.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT DISTINCT m.id_motorista, m.nome_completo
            FROM motoristas m
            WHERE m.id_motorista IN (
                SELECT id_motorista FROM devolucao
                UNION
                SELECT id_motorista FROM dispersao
                UNION
                SELECT id_motorista FROM rating
                UNION
                SELECT id_motorista FROM reposicao
                UNION
                SELECT id_motorista FROM refugo
            )
            ORDER BY m.nome_completo;
        """)

        funcionarios = cursor.fetchall()

        if request.method == 'POST':
            id_selecionado = request.form.get('id_motorista_selecionado')
            filtro_mes = request.form.get('filtro_mes')  # Pega o mês enviado pelo form

            # Query com filtro por mês
            if filtro_mes:
                query = """
                    SELECT 
                        TO_CHAR(d.data, 'YYYY-MM-DD') AS dataiso,
                        d.devolucao_porcentagem,
                        COALESCE(NULLIF(S.dispersao_km, '')::numeric, 0) AS dispersao_km,
                        r.rating,
                        COALESCE(NULLIF(p.reposicao_valor, '')::numeric, 0) AS reposicao_valor,
                        COALESCE(NULLIF(f.refugo_porcentagem, '')::numeric, 0) AS refugo_porcentagem
                    FROM devolucao d
                    LEFT JOIN dispersao s ON d.id_motorista = s.id_motorista AND d.data = s.data
                    LEFT JOIN rating r ON d.id_motorista = r.id_motorista AND d.data = r.data
                    LEFT JOIN reposicao p ON d.id_motorista = p.id_motorista AND d.data = p.data
                    LEFT JOIN refugo f ON d.id_motorista = f.id_motorista AND d.data = f.data
                    WHERE d.id_motorista = %s AND TO_CHAR(d.data, 'YYYY-MM') = %s
                    ORDER BY d.data ASC;
                """
                cursor.execute(query, (id_selecionado, filtro_mes))
            else:
                query = """
                    SELECT 
                        TO_CHAR(d.data, 'YYYY-MM-DD') AS dataiso,
                        d.devolucao_porcentagem,
                        COALESCE(NULLIF(S.dispersao_km, '')::numeric, 0) AS dispersao_km,
                        r.rating,
                        COALESCE(NULLIF(p.reposicao_valor, '')::numeric, 0) AS reposicao_valor,
                        COALESCE(NULLIF(f.refugo_porcentagem, '')::numeric, 0) AS refugo_porcentagem
                    FROM devolucao d
                    LEFT JOIN dispersao s ON d.id_motorista = s.id_motorista AND d.data = s.data
                    LEFT JOIN rating r ON d.id_motorista = r.id_motorista AND d.data = r.data
                    LEFT JOIN reposicao p ON d.id_motorista = p.id_motorista AND d.data = p.data
                    LEFT JOIN refugo f ON d.id_motorista = f.id_motorista AND d.data = f.data
                    WHERE d.id_motorista = %s
                    ORDER BY d.data ASC;
                """
                cursor.execute(query, (id_selecionado,))

            resultados = cursor.fetchall()

            # Processa resultados
            for linha in resultados:
                data = linha['dataiso']
                if data:
                    partes = data.split('-')
                    data_formatada = f"{partes[2]}-{partes[1]}-{partes[0]}"
                else:
                    data_formatada = "-"

                devolucao_raw = linha.get('devolucao_porcentagem')

                if devolucao_raw in (None, "NULL", "", "-"):
                    devolucao_porcentagem_valor = "-"
                    dispersao = "-"
                    reposicao = "-"
                    refugo = "-"
                else:
                    devolucao_porcentagem_valor = str(devolucao_raw).replace("%", "").strip()
                    dispersao = linha.get('dispersao_km')
                    reposicao = linha.get('reposicao_valor')
                    refugo = linha.get('refugo_porcentagem')

                    dispersao = "-" if dispersao in (None, "NULL") else float(dispersao)
                    reposicao = "-" if reposicao in (None, "NULL") else str(reposicao).replace('.', ',')
                    refugo = "-" if refugo in (None, "NULL") else float(refugo)
                    
                rating = linha.get('rating')
                rating = "-" if rating in (None, "NULL", "") else rating
                rating = rating.replace(',00', '') if isinstance(rating, str) else rating

                dados_formatados.append({
                    'data': data_formatada,
                    'devolucao_porcentagem': devolucao_porcentagem_valor,
                    'dispersao_km': dispersao,
                    'rating': rating.replace(',00', ''),
                    'reposicao_valor': reposicao.replace('.', ',') if isinstance(reposicao, str) else str(reposicao).replace('.', ','),
                    'refugo_porcentagem': refugo
                })
        cursor.execute("SELECT prontuario FROM telemetria WHERE id_motorista = %s", (id_selecionado,))
        resultado_prontuario = cursor.fetchone()
        prontuario = resultado_prontuario['prontuario'] if resultado_prontuario else ""

        cursor.execute("SELECT data, texto FROM observacoes WHERE id_motorista = %s", (id_selecionado,))
        observacoes = [{'data': linha['data'], 'texto': linha['texto']} for linha in cursor.fetchall()]

        cursor.close()
        conexao.close()

    indicadores = dados_formatados

    media_devolucao_porcentagem = calcular_media(dados_formatados, 'devolucao_porcentagem', ignora_percentual=True)
    media_dispersao_km = calcular_media(dados_formatados, 'dispersao_km', ignora_percentual=True)
    media_rating = calcular_media(dados_formatados, 'rating')
    soma_reposicao = sum(
        float(item['reposicao_valor'].replace(',', '.')) 
        for item in dados_formatados 
        if item['reposicao_valor'] not in (None, '', 'N/A', '-')
    )
    media_refugo = calcular_media(dados_formatados, 'refugo_porcentagem', ignora_percentual=True)

    medias = {
        'devolucao_porcentagem': media_devolucao_porcentagem,
        'dispersao_km': media_dispersao_km,
        'rating': media_rating,
        'reposicao_valor': f"{soma_reposicao:.2f}".replace('.', ','),
        'refugo_porcentagem': media_refugo
    }

    return render_template(
        'painel_supervisor.html',
        funcionarios=funcionarios,
        indicadores=dados_formatados,
        mensagem=mensagem,
        medias=medias,
        filtro_mes=filtro_mes,
        id_selecionado=id_selecionado,
        prontuario=prontuario,
        observacoes=observacoes
    )


@app.route('/explicacoes')
def explicacoes():
    if 'id_motorista' not in session:
        return redirect(url_for('login'))
    return render_template('explicacoes.html')


@app.route('/observacao', methods=['POST'])
def observacao():
    if 'id_motorista' not in session:
        return redirect(url_for('login'))

    texto = request.form.get('observacao', '').strip()
    id_motorista = session['id_motorista']
    dia = datetime.now().strftime('%d/%m/%Y %H:%M')

    if texto:
        conexao = conectar_banco()
        if conexao:
            cursor = conexao.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cursor.execute("INSERT INTO observacoes (id_motorista, data, texto) VALUES (%s, %s, %s)", (id_motorista, dia, texto))
                conexao.commit()
            except Exception as e:
                print("Erro ao salvar observação:", e)
            finally:
                cursor.close()
                conexao.close()

    return redirect(url_for('painel'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))