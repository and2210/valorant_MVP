# MVP APP — Radiante Desktop Foundation v0.20.1

Versão focada em fundação de input timing.

## Como rodar em desenvolvimento

Primeira vez:

```bat
setup_dev.bat
```

Abrir GUI sem terminal:

```bat
run_app_silent.bat
```

Abrir GUI com terminal/log:

```bat
run_dev_gui.bat
```

Abrir modo terminal:

```bat
run_dev_terminal.bat
```

## O que entrou na v0.20.1

- KCred ganho na sessão atual visível na aba `DM atual / Dashboard`.
- `core/input_timing.py` para medir duração de inputs.
- `input_timing` no `data/config.json` com `action_map` configurável.
- Captura de duração do botão esquerdo do mouse.
- Classificação inicial de tiro: tap, burst e spray longo.
- Métricas de tiro com W/S ativo.
- Métricas de tiro com crouch.
- Contagem de scroll e scroll jump.
- Medição de entradas e tempo em diagonal.
- Dados de input salvos no payload da sessão local quando a sessão é finalizada e salva.

## Observação

Esta versão mede padrões. Ela ainda não transforma spray longo, crouch longo ou uso de W/S em regras punitivas de Ranked. Essa decisão deve ser feita depois de algumas sessões reais de dados.

## SQLite

O banco local continua em:

```text
data/radiante.db
```

Ele é criado automaticamente quando necessário. JSON/CSV seguem como fallback/exportação.


## v0.20.2 - Correção visual do KCred da sessão

A aba DM atual / Dashboard agora mostra o campo "KCred desta sessão" em linha própria e em destaque dentro do painel de sessão atual, para evitar que o texto fique escondido quando a janela estiver estreita. O `run_app_silent.bat` também valida `.venv\pyvenv.cfg` antes de usar `pythonw.exe`, evitando erro de ambiente virtual incompleto.

## v0.20.5 — Correção de enriquecimento Ranked

- A importação de Ranked agora tenta usar o endpoint de MMR History para preencher Rank, RR, RRΔ e Elo quando esses campos não aparecem no lote principal de partidas.
- A importação de Ranked também pode buscar o detalhe da partida para tentar calcular FK/FD por round. Essa opção fica em Configurações > Importação Tracker/Henrik > Enriquecer Ranked.
- ACS agora tem fallback por Score / rounds quando a API não entrega ACS diretamente.
- A busca de detalhe é mais lenta e pode consumir mais chamadas da API; use importação por dia/intervalo quando estiver validando.
