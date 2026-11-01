# Backlog – Fase 1 · Base e importação

Fase 1 da especificação: **cadastros, salas, contas e ligação ao SII** (blocos 1, 2 e 8; ver `docs/especificacao/03_requisitos_funcionais.md`). Cada tarefa é pequena o bastante para uma sessão de trabalho. Ordem sugerida; marcar `[x]` quando estiver feita, com testes a passar e o código documentado conforme o `CLAUDE.md`.

## 0. Esqueleto
- [x] T0.1 Projeto Django com Docker Compose (app web + PostgreSQL + Redis), configuração por variáveis de ambiente, pytest-django a correr.
- [x] T0.2 Estrutura de apps: `core` (utilizadores, perfis, âmbitos, auditoria), `academic` (estrutura académica), `staff` (docentes), `rooms` (salas). Sem lógica ainda.
- [x] T0.3 Integração contínua: correr testes e linter a cada push.
- [x] T0.4 Completar a secção «Comandos» do `CLAUDE.md`.

## 1. Núcleo: utilizadores, perfis e auditoria
- [x] T1.1 Utilizador com perfil(is) e âmbito (Faculdade, coordenação ou docente), conforme `07_arquitetura.md` › Permissões.
- [x] T1.2 Verificação de permissões no servidor (camada reutilizável), com testes por perfil.
- [x] T1.3 Registo de auditoria genérico (quem, quando, valor anterior, valor novo, motivo).
- [x] T1.4 Autenticação local para desenvolvimento; ponto de extensão para LDAP/SSO (*questão em aberto: confirmar com os serviços informáticos*).

## 2. Estrutura académica (bloco 1)
- [x] T2.1 Faculdade, coordenação, curso (licenciatura, mestrado, doutoramento), ano letivo.
- [x] T2.2 Plano de estudos e disciplina (código, ECTS, ano, semestre, coordenação responsável, carga semestral e semanal por tipo de aula).
- [x] T2.3 Tipos de aula configuráveis (T, TP, P, L, outra) — *questão em aberto: que outros tipos existem*.
- [x] T2.4 Disciplinas transversais: declarar o mesmo programa em vários cursos e **indicar os cursos** em que é transversal; aviso quando carga ou semestre diferem (sem sugestões do sistema, D47).
- [x] T2.5 Turmas por curso e ano curricular: **uma por defeito**, modelo preparado para várias (1.º A, 1.º B). *(A junção e os grupos ficam para a fase 2.)*
- [x] T2.6 Área do gestor da PGC para introduzir e editar estes dados. *(feita em 7 partes: base da interface e tipos de aula, faculdades e anos letivos, coordenações e cursos, planos e disciplinas, horas por tipo de aula, turmas, grupos transversais)*

## 3. Docentes e contas (bloco 2)
- [x] T3.1 Docente (identificador único, categoria, coordenação) e cargos atribuídos pelo gestor. *(feita em 4 partes: modelos, categorias e cargos, docentes, cargos no formulário do docente)*
- [x] T3.2 Intervalos de horas letivas por categoria e por cargo, **com data de vigência**; função que devolve o intervalo de um docente (máximo mais baixo) — testes exaustivos. *(feita em 5 partes: função de domínio, modelo, serviços e permissão, telas, coluna na lista de docentes)*
- [x] T3.3 Parâmetro da fórmula de preparação (T + (TP+P+L) × 1,5), configurável.
- [x] T3.4 Contas por perfil geridas pelo gestor da PGC. *(feita em 4 partes: base de segurança e serviços, telas de contas, perfis na conta, conta a partir do docente)*

## 4. Salas (bloco 8)
- [x] T4.1 Sala (edifício, número, nome opcional, tipo, capacidade) introduzida pelo Património. *(feita em 2 partes: modelos e bloqueio otimista, telas)*
- [ ] T4.2 Consulta de salas por tipo e capacidade.

## 5. SII
- [ ] T5.1 Interface (contrato) de importação de matrículas, inscritos e docentes, com implementação por ficheiro CSV de teste. *Questão em aberto: que dados, por que meio e quando — não implementar a ligação real até haver resposta.*

## 6. Dados fictícios
- [ ] T6.1 Comando para carregar o conjunto descrito em `docs/dados_ficticios.md` (a parte que a fase 1 já suporta).

## Critério de fim da fase 1
O gestor da PGC introduz, com dados fictícios, uma Faculdade completa (coordenações, cursos, planos, disciplinas, disciplinas transversais, docentes, cargos, intervalos) e o Património as salas; cada perfil vê e altera só o seu âmbito; todas as alterações ficam na auditoria; testes a passar.
