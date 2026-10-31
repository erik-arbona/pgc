# PGC – Modelo de dados

> Parte da especificação da PGC (Plataforma de Gestão das Coordenações – Uni-CV). Fonte: documento do projeto, versão de 31/10/2026.

## Modelo de dados

**Entidades principais** (diagrama do documento, em texto):

| Entidade | Conteúdo | Relações |
| --- | --- | --- |
| Faculdade | Cursos e coordenações | tem cursos e coordenações |
| Coordenação | Disciplinas de vários cursos; tem docentes | gere disciplinas; tem docentes |
| Docente | Categoria, cargos e intervalo; pertence a uma coordenação | leciona através de atribuições |
| Curso | Licenciatura a doutoramento; uma ou mais turmas por ano (hoje uma) | tem plano curricular e gera turmas |
| Turma e grupos | Junção (transversais e, se houver várias, turmas do mesmo curso); divisão em grupos | recebe atribuições; tem exames |
| Atribuição | Tipo de aula (T, TP, P, L); um docente (partilha opcional, com %) | liga docente a tipo de aula de uma turma ou grupo |
| Disciplina | Plano, ano e ECTS; horas por tipo de aula | é oferecida num semestre |
| Oferta no semestre | Disciplina num semestre; pertence a uma versão do DSD | gera atribuições |
| Proposta de concurso | Com justificação; aprovada ou recusada pelo CE | se aprovada, gera atribuição |
| Época de exames | 1.ª chamada, 2.ª chamada e recurso; datas e faixas horárias | contém exames |
| Exame | Turmas, grupos e salas; responsável e júri; inscritos do SII | pertence a uma época e a uma disciplina |
| Outras atividades | Do docente, por semestre; não letivas, com horas | pertence ao docente |


A **atribuição** liga um docente a um tipo de aula de uma turma ou grupo, com a sua quota; é daqui que sai toda a carga. A **oferta no semestre** separa a disciplina do plano (estável) da disciplina lecionada num semestre (que muda), e cada oferta pertence a uma versão do DSD. Cada disciplina pertence a uma coordenação, que a gere em todos os cursos onde aparece. Quando uma proposta aprovada pelo Conselho Executivo termina com um colaborador ou um concurso, o gestor da PGC regista o docente e cria a atribuição.

O modelo inclui ainda as salas (localização – edifício e número –, nome quando tiver, tipo e capacidade) e, para cada turma ou grupo, o tipo e a capacidade de sala pedidos; ver «Perfis e fontes de dados».

Cada docente tem ainda, por semestre, as **outras atividades** atribuídas pelo coordenador (tipo — complementos de ensino, investigação ou gestão e serviços —, descrição e horas), que entram na carga total, como no DSD em Excel.

Cada disciplina pertence a um ano de um curso e é gerida pela coordenação da sua área: a Análise Matemática I de EIC, por exemplo, é atribuída pelo grupo disciplinar de Matemática. Como cada docente pertence a uma coordenação e as suas disciplinas passam por ela, a carga total do docente fica visível num só sítio. Cada curso tem um plano de estudos e, em cada ano curricular, uma ou mais turmas. Hoje cada curso tem uma turma por ano (por exemplo, quatro anos, quatro turmas), e o sistema funciona assim por defeito, sem passos extra nem letras nas turmas; o modelo admite desde o início várias turmas no mesmo ano (por exemplo, 1.º A e 1.º B), para quando um curso abrir uma segunda turma. Nesse caso, cada turma recebe as suas atribuições e conta as suas horas, e o coordenador pode juntar turmas do mesmo curso numa disciplina, com as mesmas regras de contagem da junção de turmas; cada ano tem um conjunto de disciplinas no 1.º semestre e outro no 2.º. No plano, cada disciplina tem uma carga semestral e uma carga semanal, distribuída por tipo de aula. Em cada ano letivo, o coordenador atribui um docente a cada tipo de aula das disciplinas da sua área; conforme as matrículas, pode dividir a turma em grupos e pode juntar turmas, mesmo de cursos diferentes, quando se trata de uma disciplina transversal (por exemplo, a teórica de Introdução à Programação dada em conjunto a EIC e EEC, que se separam nas práticas em 3 grupos de EIC e 2 de EEC).

**Disciplinas transversais.** Algumas disciplinas existem com o mesmo programa em vários cursos, como Introdução à Programação ou Análise Matemática. O gestor da PGC declara, ao introduzir os planos de estudos, que disciplinas de cursos diferentes são a mesma disciplina transversal e indica os cursos em que ela é transversal. A junção de turmas é validada contra essa lista: só se podem juntar turmas dos cursos indicados. Por exemplo, se o gestor declarar uma disciplina transversal apenas em EEC e EIC, o coordenador só pode juntar turmas de EEC e de EIC nessa disciplina, e o sistema recusa qualquer outra turma. A mesma validação aplica-se à junção de turmas nos exames. O sistema sugere candidatas (nome parecido e a mesma carga ou os mesmos ECTS em planos diferentes) e o gestor confirma ou rejeita cada uma, porque os nomes nem sempre são escritos da mesma forma. Se a carga por tipo de aula for diferente entre os planos, o sistema avisa antes de aceitar a junção. Só se juntam turmas que tenham a disciplina no mesmo semestre: Introdução à Programação, por exemplo, é do 1.º semestre em EIC e do 2.º em TM, por isso as turmas destes dois cursos não se juntam. O coordenador decide a distribuição: se, em cada ano letivo, junta ou não as turmas e para que tipo de aula (por exemplo, teóricas juntas e práticas em grupos por curso). Quando as turmas estão juntas, o exame marca-se uma vez e ocupa o dia em todas elas.

