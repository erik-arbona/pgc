# Glossário da PGC

Termos do domínio, o que significam na PGC e o nome proposto no código. Os nomes no código são uma proposta inicial: se se mudarem, muda-se aqui primeiro.

| Termo | Significado na PGC | Nome no código (proposta) |
| --- | --- | --- |
| PGC | Plataforma de Gestão das Coordenações | `pgc` |
| Faculdade | Unidade orgânica que integra cursos e coordenações | `Faculty` |
| Coordenação (grupo disciplinar) | Gere as disciplinas da sua área em todos os cursos onde aparecem; tem docentes | `Coordination` |
| Coordenador | Responsável por uma coordenação; é também o diretor de curso | perfil `coordinator` |
| Diretor de curso | Papel exercido pelo coordenador; dá acesso à vista por curso (leitura do que é de outras coordenações) | — (não é perfil próprio) |
| Gestor da PGC | Perfil que introduz docentes, cargos, planos, disciplinas, disciplinas transversais, intervalos, épocas e faixas de exames, e gere contas; um por Faculdade ou para várias | perfil `pgc_manager` |
| Conselho Executivo (CE) | Aprova ou recusa propostas de concurso e justificações; fecha o DSD de cada coordenação | perfil `executive_board` |
| Serviços Académicos | Introduzem matrículas e inscritos (de preferência do SII) | perfil `academic_services` |
| Património | Introduz as salas (localização, nome, tipo, capacidade) | perfil `facilities` |
| Consulta | Só leitura (inclui quem faz os horários) | perfil `viewer` |
| Docente | Professor; pertence a uma coordenação; vê só a sua distribuição | `Teacher` |
| Categoria | Licenciado, mestre, doutor | `Teacher.category` |
| Cargo | Função que altera o intervalo de horas (atribuída pelo gestor da PGC) | `Position` |
| Intervalo de horas letivas | Mínimo e máximo anual (horas semanais somadas dos dois semestres) por categoria e por cargo; aplica-se o de máximo mais baixo | `LoadRange` (com vigência) |
| Curso | Licenciatura, mestrado ou doutoramento, com plano de estudos | `Course` |
| Plano de estudos | Disciplinas por ano e semestre de um curso | `StudyPlan` |
| Disciplina (UC) | Unidade do plano: código, ECTS, programa, coordenação, carga semestral e semanal por tipo de aula | `Subject` |
| Tipo de aula | Teórica (T), teórico-prática (TP), prática (P), laboratorial (L), outra | `ClassType` |
| Disciplina transversal | A mesma disciplina, com o mesmo programa, em cursos diferentes e no mesmo semestre; o gestor indica em que cursos pode ter turmas juntas | `CrossCourseSubject` |
| Ano letivo | Período anual do DSD e dos exames | `AcademicYear` |
| Oferta no semestre | A disciplina lecionada num semestre de um ano letivo; pertence a uma versão do DSD | `Offering` |
| Turma | Conjunto de estudantes de um curso e ano curricular; hoje uma por ano, o modelo admite várias (1.º A, 1.º B) | `ClassGroup` |
| Grupo | Divisão de uma turma (normalmente para P ou L) | `SubGroup` |
| Junção de turmas | Várias turmas numa só aula ou exame: turmas de cursos diferentes só em disciplinas transversais e entre os cursos indicados; turmas do mesmo curso por decisão do coordenador | `Merge` / relação |
| Atribuição | Liga um docente a um tipo de aula de uma turma ou grupo; normalmente um docente, partilha opcional com percentagem | `Assignment` |
| Quota (percentagem de partilha) | Parte de um tipo de aula partilhado que cabe a cada docente; as quotas somam 100% | `Assignment.share` |
| Regente | Docente responsável pela disciplina | `Offering.lead_teacher` |
| Horas letivas | Horas de aula atribuídas; as únicas validadas contra o intervalo | — |
| Horas de preparação | Calculadas: T + (TP + P + L) × 1,5 (parâmetro) | — |
| Componente não letiva / outras atividades | Complementos de ensino, investigação, gestão e serviços, com descrição e horas, por semestre | `OtherActivity` |
| Horas extra | Total de horas letivas menos o máximo do intervalo; só se o docente aceitar; registadas pelo coordenador | `ExtraHours` |
| Estado da carga | Abaixo da mínima, no intervalo, na máxima, acima da máxima | `LoadStatus` |
| Proposta de concurso | Disciplina que o coordenador não pode atribuir; justificação obrigatória; decisão do CE | `CompetitionRequest` |
| Colaborador | Docente externo obtido quando o CE aprova a proposta | — |
| Fecho do DSD | O CE fecha o DSD de uma coordenação; cria versão imutável | `DsdVersion` |
| Sala | Localização (edifício, número), nome quando tiver, tipo e capacidade | `Room` |
| Época de exames | 1.ª chamada, 2.ª chamada, recurso, com datas | `ExamPeriod` |
| Faixa horária | Bloco de exame definido pelo gestor (p. ex. 09:00-11:00) | `ExamSlot` |
| Exame | Disciplina, época, turmas, grupos (com nº de estudantes), dia, faixa, salas, responsável, júri, inscritos do SII | `Exam` |
| Docente responsável | Por defeito o docente da disciplina no DSD; alterável | `Exam.responsible` |
| Júri | Docentes da coordenação escolhidos para o exame | `Exam.jury` |
| SII | Sistema de informação académica da Uni-CV (matrículas, inscritos, listas por exame) | integração `sii` |
| Vista por curso | DSD e exames de um curso, de todas as coordenações, com filtros | — |
