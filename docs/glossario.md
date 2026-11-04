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
| Conselho Executivo (CE) | Aprova ou recusa propostas de concurso e justificações de carga; não abre, não fecha nem altera o DSD (D43) | perfil `executive_board` |
| Serviços Académicos | Introduzem matrículas e inscritos (de preferência do SII) | perfil `academic_services` |
| Património | Introduz as salas (localização, nome, tipo, capacidade) | perfil `facilities` |
| Consulta | Só leitura (inclui quem faz os horários) | perfil `viewer` |
| Docente | Professor; pertence a uma coordenação; vê só a sua distribuição | `Teacher` |
| Categoria | Licenciado, mestre, doutor | `Teacher.category` |
| Cargo | Função que altera o intervalo de horas (atribuída pelo gestor da PGC) | `Position` |
| Intervalo de horas letivas | Mínimo e máximo anual (horas semanais somadas dos dois semestres) por categoria e por cargo; aplica-se o de máximo mais baixo | `LoadRange` (com vigência) |
| Curso | Licenciatura, mestrado ou doutoramento, com plano de estudos; tem, opcionalmente, uma coordenação responsável da mesma Faculdade | `Course` |
| Coordenação responsável (do curso) | Coordenação que dirige o curso; o seu coordenador é o diretor de curso (D10, D67). Não é a coordenação de cada disciplina | `Course.responsible_coordination` |
| Referência no SII | Valor opaco que o SII usa para um curso ou uma disciplina; escrito pelo gestor, único por curso e por plano de estudos (D66, D68) | `sii_ref` |
| Plano de estudos | Disciplinas por ano e semestre de um curso | `StudyPlan` |
| Disciplina (UC) | Unidade do plano: código, ECTS, programa, coordenação, carga semestral e semanal por tipo de aula | `Subject` |
| Tipo de aula | Teórica (T), teórico-prática (TP), prática (P), laboratorial (L), outra | `ClassType` |
| Carga semanal por tipo de aula | Horas semanais de um tipo de aula numa disciplina; a soma é a carga semanal da disciplina | `SubjectClassLoad` |
| Disciplina transversal | A mesma disciplina, com o mesmo programa, em cursos diferentes e no mesmo semestre; o gestor indica em que cursos pode ter turmas juntas | `CrossCourseSubject` |
| Ano letivo | Período anual do DSD e dos exames | `AcademicYear` |
| Oferta no semestre | A disciplina lecionada num semestre de um DSD (uma por semestre e disciplina), com as turmas que a frequentam e o regente; pertence à coordenação da disciplina (D87) | `Offering` |
| Percurso (variante) | Divisão de um plano de estudos a partir de um ano curricular (EIC: TIC e PSI no 4.º ano; TM: Multimédia e Audiovisual). Cada percurso tem a sua turma; a disciplina é comum ou de um percurso (D75, D79) | `Track` |
| Matrícula | Número de estudantes matriculados numa turma num ano letivo, estimado (quando se faz o DSD) e atualizado com o real (quando chega); só números, sem nomes (D66, D76, D81) | `Enrollment` |
| Turma | Coorte de estudantes de um curso que entra num ano letivo e sobe um ano curricular por ano; hoje uma por entrada, o modelo admite várias (1.º A, 1.º B); mantém o plano de estudos com que entrou; pode terminar (último ano letivo) | `ClassGroup` |
| Grupo | Divisão de uma turma para um tipo de aula (normalmente P ou L), numerada a partir de 1; é uma unidade letiva própria e pode juntar-se a grupos de outras turmas (D90) | `SubGroup` |
| Junção de turmas | Várias turmas numa só aula ou exame: turmas de cursos diferentes só em disciplinas transversais e entre os cursos indicados; turmas do mesmo curso por decisão do coordenador | `Merge` / relação |
| Atribuição | Liga um docente a um tipo de aula de uma turma ou grupo; normalmente um docente, partilha opcional com percentagem | `Assignment` |
| Quota (percentagem de partilha) | Parte de um tipo de aula partilhado que cabe a cada docente; as quotas somam 100% | `Assignment.share` |
| Regente | Docente responsável pela disciplina | `Offering.lead_teacher` |
| Horas letivas | Horas de aula atribuídas, semanais (por docente e semestre); as únicas validadas contra o intervalo. Junção conta uma vez, cada grupo conta uma vez (D70) | `TeacherTeachingHours` |
| Horas de preparação | Calculadas por docente: T + (TP + P + L) × 1,5 (parâmetro, pesos por tipo de aula); acompanham cada hora letiva, repetida por grupo (D61, D71) | — |
| Componente não letiva / outras atividades | Complementos de ensino, investigação, gestão e serviços, com descrição e horas, por semestre | `OtherActivity` |
| Horas extra | Total de horas letivas menos o máximo do intervalo (calculadas por `assess_load`, D74); só se o docente aceitar; registadas pelo coordenador | `ExtraHours` |
| Carga anual | Soma das horas letivas semanais dos dois semestres, comparada com o intervalo em vigor na data de referência (D12, D58, D72) | `AnnualLoad` |
| Estado da carga | Abaixo da mínima, no intervalo, na máxima, acima da máxima, ou «sem intervalo» quando nenhuma regra vigora (D74) | `LoadStatus` |
| Proposta de concurso | Disciplina que o coordenador não pode atribuir; justificação obrigatória; decisão do CE | `CompetitionRequest` |
| Colaborador (habitual) | Docente externo que já leciona na Universidade e pode ser convidado pelo CE; os outros tipos são o docente a tempo inteiro e o docente de concurso; cada tipo tem intervalo de horas próprio e configurável | — |
| DSD | Distribuição de Serviço Docente de um ano letivo, criada pelo gestor da PGC (um por ano letivo), com os dois semestres; cada semestre abre-se e fecha-se por coordenação (D43) | `Dsd` |
| Fecho do DSD | O gestor da PGC fecha um semestre de uma coordenação (ou de todas); cria versão imutável; depois só ele altera, numa nova versão (D43) | `DsdVersion` |
| Unidade letiva | Aula de um tipo (T, TP, P, L) de uma oferta, para um público: uma turma, várias turmas juntas ou um grupo; é a que recebe o docente. Por defeito, uma por turma e tipo de aula (D89) | `TeachingUnit` |
| Sala | Localização (edifício, número), nome quando tiver, tipo e capacidade | `Room` |
| Época de exames | 1.ª chamada, 2.ª chamada, recurso, com datas | `ExamPeriod` |
| Faixa horária | Bloco de exame definido pelo gestor (p. ex. 09:00-11:00) | `ExamSlot` |
| Exame | Disciplina, época, turmas, grupos (com nº de estudantes), dia, faixa, salas, responsável, júri, inscritos do SII | `Exam` |
| Docente responsável | Por defeito o docente da disciplina no DSD; alterável | `Exam.responsible` |
| Júri | Docentes da coordenação escolhidos para o exame | `Exam.jury` |
| SII | Sistema de informação académica da Uni-CV (matrículas, inscritos, listas por exame) | integração `sii` |
| Vista por curso | DSD e exames de um curso, de todas as coordenações, com filtros | — |
