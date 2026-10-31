# PGC – Módulo DSD

> Parte da especificação da PGC (Plataforma de Gestão das Coordenações – Uni-CV). Fonte: documento do projeto, versão de 31/10/2026.

## Módulo DSD: regras de cálculo da carga horária

A carga de cada docente soma as horas de cada aula atribuída, ponderadas pela sua quota de partilha. A unidade de atribuição é o **tipo de aula** (teórica, teórico-prática, prática, laboratorial ou outra) de uma disciplina, dada a uma **turma ou grupo**.

```latex
C_d = \sum_{a \in A_d} h_a \cdot s_{a,d}
```

Aqui, `h_a` são as horas semanais da componente `a` no plano curricular e `s_{a,d}` é a quota do docente `d` nessa atribuição (1 se estiver sozinho, que é o caso normal). Normalmente cada tipo de aula tem um só docente (por exemplo, um para a teórica e outro para as práticas), e cada um soma as horas completas do que dá; a quota só aparece quando o coordenador opta por partilhar o mesmo tipo de aula da mesma turma ou grupo entre dois ou mais docentes, por exemplo 50% e 50%. As horas de cada turma ou grupo contam uma vez por cada turma ou grupo lecionado.

| Cenário | Como se regista | Efeito na carga |
| --- | --- | --- |
| Disciplina com uma turma | 1 turma, 1 docente | Horas do plano, uma vez |
| Junção de turmas | Várias turmas, mesmo de cursos diferentes, numa só oferta | O tipo de aula comum (por exemplo, a teórica) conta uma vez, não por turma juntada |
| Divisão em grupos | Turma dividida em N grupos | O tipo de aula dividido (normalmente prática ou laboratorial) conta N vezes; por exemplo, 3 grupos de EIC e 2 de EEC contam 5 vezes |
| Grupos com docentes diferentes | Cada grupo tem o seu docente | Cada docente recebe só os seus grupos |
| Disciplina partilhada | Vários docentes na mesma turma | Exceção, só quando o coordenador partilha: as quotas somam 100% do tipo de aula |
| Docente obtido por concurso ou colaborador | Colaborador ou docente de concurso, registado pelo gestor da PGC | Entra na carga desse docente como as restantes |
| Disciplina de mestrado ou doutoramento | Curso de mestrado ou doutoramento, com os seus planos | Entra na carga do semestre como as restantes |

O DSD de cada docente regista, para cada semestre, três componentes:

- **Horas letivas:** as horas de aula atribuídas, por tipo de aula.
- **Horas de preparação**, calculadas pelo sistema com a fórmula preparação = horas teóricas semanais + (horas teórico-práticas, práticas e laboratoriais semanais) × 1,5. A fórmula fica como parâmetro, para poder ser ajustada sem alterar o código.
- **Componente não letiva**, atribuída pelo coordenador, que introduz para cada atividade a descrição e as horas, caso a caso: complementos de ensino (orientação de TFC, atendimento, etc.), investigação (com o projeto de investigação, o programa doutoral, etc.) e gestão e serviços (coordenações, órgãos, projetos, extensão).

O intervalo anual mínimo e máximo valida apenas as horas letivas; a preparação e a componente não letiva não contam para ele e somam-se no total geral do docente.

Cada docente tem um intervalo anual de horas letivas, com um mínimo e um máximo, que resulta da sua categoria e dos seus cargos: o gestor da PGC define um intervalo para cada categoria e para cada cargo, e, quando um docente tem vários, aplica-se o intervalo com o máximo mais baixo. O intervalo mede-se em horas letivas semanais somadas dos dois semestres, como no DSD em Excel: o sistema soma as horas semanais de cada semestre, calcula o estado da carga sobre esse total e mostra também o detalhe de cada semestre. Estes valores são parâmetros introduzidos no sistema, não valores fixos no código: podem variar, e cada alteração fica registada com a data e o utilizador. Uma alteração aplica-se também ao ano letivo em curso, e os avisos de carga são recalculados; os DSD já fechados conservam os valores com que foram fechados. As horas extra (o total de horas letivas menos o máximo do intervalo) só se atribuem se o docente as aceitar, e é o coordenador que as regista no sistema. Se o docente não aceitar, ou se não houver docente suficiente na coordenação, o coordenador propõe a disciplina a concurso, com justificação, ao Conselho Executivo.

O sistema mostra ao coordenador o estado da carga anual de cada docente, em quatro níveis. Abaixo da mínima, o coordenador tem de registar o motivo; o Conselho Executivo vê-o nos relatórios e pode recusá-lo, devolvendo o caso ao coordenador.

| Estado | Condição | O que o sistema faz |
| --- | --- | --- |
| Abaixo da mínima | Carga inferior à mínima | Avisa e exige que o coordenador registe o motivo, que o Conselho Executivo pode recusar |
| No intervalo | Atingiu a mínima e ainda não chegou à máxima | Mostra a carga como normal, sem aviso |
| Na máxima | Carga igual à máxima | Assinala que o docente está no limite: qualquer hora a mais passa a ser hora extra |
| Acima da máxima | Carga superior à máxima | Avisa: as horas extra só se atribuem se o docente as aceitar; se não aceitar, o coordenador propõe a disciplina a concurso |

## Módulo DSD: propostas de concurso, fecho e validações

Cada coordenador vê as disciplinas da sua coordenação, em todos os cursos, e os docentes da coordenação, e faz a distribuição. Quando não pode atribuir uma disciplina a um docente da coordenação (não há docente com o perfil, os que há não chegam para a carga horária ou não aceitam horas extra), propõe-na a concurso com uma justificação obrigatória. Um utilizador do Conselho Executivo da Faculdade analisa a proposta: pode recusá-la, por exemplo por não estar devidamente justificada, e o coordenador recebe um aviso por correio eletrónico e volta a tratá-la; ou aprová-la, resolvendo-a com um colaborador ou mandando-a a concurso docente. Enquanto espera, a disciplina fica no estado «A concurso», visível nos relatórios e na lista do gestor da PGC. Com o resultado, o gestor da PGC introduz o docente na disciplina, turma, ano e curso, e a carga atualiza-se. Quando a distribuição está completa, o coordenador ajusta o DSD e o Conselho Executivo fecha o DSD dessa coordenação; a partir daí, quem faz os horários vê a informação de que precisa.

O utilizador do Conselho Executivo tem relatórios próprios: disciplinas a concurso e respetivas justificações, docentes abaixo da carga mínima e respetivos motivos, docentes abaixo da máxima e docentes com horas extra. Pode recusar tanto uma proposta de concurso como a justificação de uma carga abaixo da mínima.

**Calendário e notificações.** O DSD de cada ano letivo segue um calendário definido no sistema: abertura, prazo dos coordenadores, decisão do Conselho Executivo sobre as propostas e fecho. O sistema avisa por correio eletrónico quando um prazo se aproxima, quando uma proposta ou justificação é recusada e quando o DSD é fechado.

**Depois do fecho.** Os resultados dos concursos chegam muitas vezes depois do fecho. Por isso, o DSD fechado aceita alterações do gestor da PGC e do Conselho Executivo, e cada alteração cria uma nova versão, com data, autor e motivo.

**Novo ano a partir do anterior.** Para não começar do zero, o coordenador pode iniciar o DSD de um novo ano letivo a partir de uma cópia do DSD de um ano anterior da sua coordenação. A cópia traz as atribuições de docentes por disciplina, tipo de aula, turma e grupo, as junções e divisões de turmas, o tipo e a capacidade de sala pedidos e as outras atividades, e fica totalmente editável. O sistema recalcula tudo com os dados do novo ano (matrículas, planos de estudos e intervalos de horas em vigor) e assinala o que deixou de bater certo: disciplinas que saíram do plano ou mudaram de carga, docentes que já não estão na coordenação e grupos que já não correspondem às matrículas. O DSD do ano anterior fica intacto.

O sistema avisa antes de o Conselho Executivo fechar o DSD de uma coordenação quando:

- uma disciplina, turma ou grupo fica sem docente;
- uma disciplina proposta a concurso não tem justificação;
- a carga de um docente passa da máxima (horas extra por aceitar) ou fica abaixo da mínima (exige justificação);
- as quotas de um tipo de aula não somam 100%;
- uma turma ou grupo não tem sala indicada, ou nenhuma sala existente tem o tipo e a capacidade necessários;
- uma proposta de concurso continua sem decisão do Conselho Executivo.

