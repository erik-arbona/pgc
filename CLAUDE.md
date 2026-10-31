# PGC – Plataforma de Gestão das Coordenações (Uni-CV)

Aplicação web para as coordenações da Universidade de Cabo Verde elaborarem, validarem e publicarem:

- o **DSD** (Distribuição de Serviço Docente) de cada ano letivo;
- o **calendário de exames** (1.ª chamada, 2.ª chamada e recurso).

Os dois módulos assentam num **núcleo partilhado** (estrutura académica, docentes, turmas, salas, utilizadores e calendário). Os horários entram mais tarde, como outro módulo.

Promotor: ICUB.

## Onde está a especificação

Lê **sempre** a parte da especificação que toca a tarefa antes de escrever código:

| Ficheiro | Conteúdo |
| --- | --- |
| `docs/especificacao/01_visao_geral.md` | Problema, objetivos, âmbito, módulos |
| `docs/especificacao/02_perfis_e_dados.md` | Perfis e quem introduz cada dado |
| `docs/especificacao/03_requisitos_funcionais.md` | Os 10 blocos funcionais e a fase de cada um |
| `docs/especificacao/04_modelo_de_dados.md` | Entidades e relações |
| `docs/especificacao/05_dsd_regras.md` | Cálculo da carga, intervalos, horas extra, concursos, fecho, validações |
| `docs/especificacao/06_exames.md` | Calendário de exames |
| `docs/especificacao/07_arquitetura.md` | Requisitos não funcionais, componentes, permissões, auditoria, integrações |
| `docs/especificacao/08_plano.md` | Fases, recursos, riscos |
| `docs/especificacao/09_criterios_e_questoes.md` | Critérios de sucesso e questões em aberto |
| `docs/glossario.md` | Termos do domínio e nome a usar no código |
| `docs/decisoes.md` | Decisões tomadas (prevalecem sobre o resto se houver conflito) |
| `docs/backlog_fase1.md` | Tarefas da fase atual |

## Regras de trabalho

1. **Não inventar regras de negócio.** Se a especificação não responde, pára e pergunta. Não preenchas lacunas com suposições.
2. Se uma tarefa tocar numa **questão em aberto** (`09_criterios_e_questoes.md`), assinala-o antes de implementar.
3. **Tarefas pequenas:** primeiro um plano curto, depois o código, depois os testes. Não alteres ficheiros fora do âmbito da tarefa.
4. **Regras de cálculo** (carga, intervalo, horas extra, junções, grupos, capacidade de salas, conflitos de exames) vivem em módulos de domínio sem dependência de views ou templates, e têm **testes unitários obrigatórios**.
5. **Permissões verificadas sempre no servidor**, nunca só na interface.
6. **Parâmetros, não constantes:** intervalos de horas, fórmula de preparação (T + (TP+P+L) × 1,5) e faixas horárias de exames são dados configuráveis, com data de vigência quando aplicável.
7. **Auditoria:** cada alteração de dados de negócio regista quem, quando, valor anterior, valor novo e motivo.
8. **Sem dados reais** no repositório: só dados fictícios (`docs/dados_ficticios.md`).
9. No fim de cada tarefa: testes a passar, código documentado (ver «Documentação do código») e, se se tomou uma decisão nova, uma linha em `docs/decisoes.md`.

## Stack

- Python 3 + Django (monólito modular: uma app Django por bloco funcional; núcleo comum para utilizadores, perfis, âmbitos e auditoria).
- PostgreSQL (restrições na base de dados para integridade e concorrência: p. ex. um exame por turma, época e dia; um exame por sala, data e hora).
- Interface: templates Django + HTMX, organizada por vistas (não grelha tipo Excel).
- Celery + Redis para correio eletrónico, sincronização com o SII e relatórios pesados.
- Contentores (Docker Compose) para desenvolvimento, teste e produção.
- Testes com pytest (pytest-django).

## Convenções

- **Todo o código e todos os comentários em inglês**: modelos, campos, funções, variáveis, docstrings, comentários, nomes de testes e mensagens de commit. **Interface (textos que o utilizador vê) e documentação em `docs/` em português europeu**, com textos da interface marcados para tradução (`gettext`). Os termos do domínio seguem o glossário (`docs/glossario.md`), que indica o nome no código.

## Documentação do código (obrigatória)

O código tem de estar bem documentado. Uma tarefa não está terminada sem isto:

- **Docstring em cada módulo**: o que contém e a secção da especificação que implementa (p. ex. `Implements: docs/especificacao/05_dsd_regras.md – load calculation`).
- **Docstring em cada classe, função e método públicos** (estilo Google): o que faz, `Args`, `Returns`, `Raises` e, nas regras de negócio, a regra em causa com referência à decisão (`docs/decisoes.md`, p. ex. `See D13`).
- **Modelos Django**: docstring na classe, `help_text` e `verbose_name` em cada campo, e explicação de cada restrição (`constraints`) e índice.
- **Type hints** em todas as assinaturas.
- **Comentários para explicar o porquê**, não o quê: regras não óbvias, casos-limite, decisões de desenho. Sem comentários que repitam o código.
- **Testes com nomes e docstrings que descrevam a regra testada** (p. ex. `test_lowest_maximum_range_applies_when_teacher_has_several_positions`).
- Quando uma alteração muda o comportamento, atualizar as docstrings e comentários afetados na mesma tarefa.
- Cada app Django tem um `README.md` curto (em inglês): responsabilidade, modelos principais e dependências.
- Bloqueio otimista (campo de versão) nas entidades editadas por várias pessoas (turma, grupo, sala, atribuição, exame).
- Turmas: o modelo admite **várias turmas por curso e ano**; por defeito cria-se uma só e a interface não mostra letra enquanto houver uma.
- Atribuição: **um docente por tipo de aula de cada turma ou grupo**; a partilha com percentagem é opcional e só aparece quando o coordenador a pede.

## Comandos

> A completar quando o esqueleto do projeto existir (arrancar, migrar, carregar dados fictícios, correr testes).
