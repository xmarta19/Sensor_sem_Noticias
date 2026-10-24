# Sensor sem notícias

## Problema e utilizador
Um técnico da Human Experience tem vários dispositivos e quer saber **há quanto tempo cada um não envia uma leitura válida**, para decidir qual verificar primeiro. O cenário é hipotético; não se atribui localização a nenhum sensor.

## Como executar
1. **Python 3.10+** 
2. **Ambiente virtual** (Opcional)
   `python -m venv .venv` e ativar com
   `.venv\Scripts\Activate.ps1` (Windows PowerShell) ou `source .venv/bin/activate` (Linux/macOS).

3. **Instalar as dependências:** `pip install -r requirements.txt`.
2. **Modo offline (ficheiro JSON):** colocar o ficheiro de contingência na pasta `data/` ou carregá-lo na interface.
3. **Modo online:** renomear `.env.example` para `.env` e preencher `HE_EMAIL` e `HE_PASSWORD` com uma conta válida.
4. **Executar:** `streamlit run app.py`
5. **Testes:** `python -m pytest` e `python scripts/cenarios.py` gera `TESTES.md`.


## Regra
`atraso = instante de referência − instante da última observação válida`
- Instante = `data.createdAt`
- Observação Válida = pelo menos uma métrica escolhida (temperatura, humidade, luz) com valor numérico não `null`.
- **Em dia** se atraso ≤ limiar. 
- **Sem notícias** se atraso > limiar.
- **Sem dados** se não há leitura válida no período.
- Episódios: intervalos entre leituras consecutivas acima do limiar, mais o silêncio em curso.
- Duplicados são removidos e contados e linhas desordenadas são ordenadas.

Cada dispositivo mostra também as **leituras ao longo do tempo** (gráfico por métrica ou tabela), com escolha das métricas. O gráfico não interpola ausências e sombreia os episódios sem notícias.

**Parâmetros alteráveis:** dispositivos, período (1–24 h), limiar (5–120 min), métricas e instante de referência.

## Origem e modo dos dados
- **Online:** `https://sensorblock.humanexperience.pt`
- **Histórico:** recorte de 20–21/10/2026 fornecido pelo docente. Não reflete o tempo real.

## Limitações
- O limiar é uma hipótese e não garante estado do equipamento ou o seu funcionamento.
- "Sem notícias" não diz a causa (rede, energia, firmware, sensor).
- No modo online só se consulta o período escolhido, por isso a leitura anterior ao período é desconhecida.

## Uso de IA
Usei o IA para preparar um resumo do seminário e para conceber e escrever o código desta apricação e os testes. _
Executei todos os testes (pytest e scripts/cenarios.py) e simplifiquei e melhorei a usabilidade da aplicação, permitindo por exemplo, ver as leituras ao longo do tempo.

## Código reutilizado
Bibliotecas: Streamlit, requests, pandas, Altair. 

## Versão
Versão demonstrada na aula: versão final da aplicação, igual à do vídeo. Correções posteriores até à entrega: Sem alterações.
