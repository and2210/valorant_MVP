# Radiante Daily

Este projeto é o MVP APP / Radiante Daily, um app desktop local em Python/PySide6 para treino de Valorant, KCred, SQLite, importação Henrik, calendário, Ranked e Deathmatch.

## Prioridade atual

1. Estabilizar app desktop.
2. Consolidar SQLite.
3. Organizar abas.
4. Estabilizar importação Ranked/Deathmatch.
5. Melhorar fluxo de execução sem recompilar dist.
6. Só depois evoluir Daily Core, aba Treino, maestria e Ranked Tickets.

## Não implementar agora

- sistema de tickets Ranked
- coach
- OBS
- Google Calendar
- KovaaK/Aimlabs
- mobile
- machine learning
- novas integrações externas

## Regras de desenvolvimento

Antes de alterar código, explique o plano.
Não implementar feature fora do escopo solicitado.
Preferir alterações pequenas e testáveis.
Preservar compatibilidade com o fluxo atual de execução por .bat.
Não depender de PyInstaller durante desenvolvimento.
Não quebrar leitura de dados antigos.
Manter SQLite como fonte principal progressiva.
Manter JSON/CSV como fallback, cache ou exportação quando aplicável.

## Henrik API

Antes de alterar importação Henrik, consultar o MCP `henrikdev-api`.
O repositório/documentação Henrik é referência técnica, não dependência direta do app.
Separar dado bruto de dado normalizado.
Proteger duplicidade por match_id.
Salvar payload bruto quando possível.
Normalizar defensivamente.
Não assumir que FB/FD vem como campo direto.
Calcular FB/FD a partir dos eventos de kill por round quando disponíveis.
Usar PUUID para identificar jogador.
Se v4/match falhar, usar fallback seguro sem quebrar importação.

## Fluxo esperado

1. Auditar.
2. Planejar.
3. Alterar o mínimo necessário.
4. Rodar testes manuais ou automatizados.
5. Mostrar diff.
6. Explicar o que mudou.