# PGC – Visão geral

> Parte da especificação da PGC (Plataforma de Gestão das Coordenações – Uni-CV). Fonte: documento do projeto, versão de 31/10/2026.

## Resumo executivo

Propõe-se construir a **Plataforma de Gestão das Coordenações (PGC)**: uma aplicação web única, com base de dados central, onde as coordenações (grupos disciplinares) de toda a Universidade fazem, sobre os mesmos dados, o trabalho que hoje fazem em ficheiros soltos. A PGC entra em funcionamento com dois módulos:

- **DSD (Distribuição de Serviço Docente):** cada coordenação atribui docentes às disciplinas da sua área; o sistema calcula a carga de cada docente, valida-a face ao seu intervalo de horas e acompanha as propostas de concurso até ao fecho pelo Conselho Executivo.
- **Calendário de exames:** as coordenações marcam, num calendário único e partilhado, os exames de 1.ª chamada, 2.ª chamada e recurso, sem conflitos de turma, sala ou júri.

Hoje os dois processos fazem-se em ficheiros Excel e Word, um por coordenação. Os ficheiros multiplicam-se em cópias, os nomes e os totais deixam de coincidir, os pedidos e as confirmações entre coordenações fazem-se fora dos ficheiros, e uma alteração numa turma obriga a refazer trabalho em vários sítios.

A PGC traz cinco ganhos:

- **Uma única fonte de verdade** para cursos, planos, disciplinas, docentes, turmas, grupos e salas, em que cada dado é introduzido uma vez por quem é responsável por ele e serve todos os módulos.
- **Carga horária calculada** por tipo de aula, incluindo disciplinas de outros cursos, de mestrado e de doutoramento.
- **Propostas de concurso justificadas**, que o Conselho Executivo aprova ou recusa, com estado e histórico.
- **Calendário de exames partilhado** entre todas as coordenações, sem troca de ficheiros nem datas «a confirmar».
- **Rastreabilidade**: quem alterou o quê, quando e porquê, com versões por ano letivo.

A PGC é para todas as coordenações da Universidade, não apenas para o GD EITM. Implementa-se por fases, com um piloto num grupo de Faculdades, em paralelo com os ficheiros atuais, antes de se estender a toda a Universidade. Sobre o mesmo núcleo de dados entrará depois o módulo de horários, que decide quando e onde é cada aula a partir do DSD fechado.

## Contexto e problema

As coordenações da Uni-CV gerem todos os anos dois processos que dependem dos mesmos dados (cursos, planos de estudos, disciplinas, docentes, turmas e salas), mas que hoje se fazem em ficheiros separados: a distribuição de serviço docente (DSD) e o calendário de exames.

Cada Faculdade integra coordenações (grupos disciplinares). Cada coordenação é responsável pelas disciplinas da sua área em todos os cursos onde aparecem: por exemplo, é o grupo disciplinar de Matemática, e não a coordenação de EIC, que atribui a Análise Matemática I de EIC a um docente seu e marca o seu exame. Uma disciplina pode ter vários docentes e um docente pode lecionar várias disciplinas, de cursos diferentes, incluindo mestrado e doutoramento. Por isso, a mesma turma recebe disciplinas, docentes e exames de várias coordenações.

**DSD.** A carga horária vem do plano de estudos, mas a carga efetiva depende de como as turmas se organizam em cada ano letivo: turma única, junção de turmas, divisão em grupos, grupos com docentes diferentes, disciplina partilhada. Em Excel, cada coordenação faz o seu ficheiro, com fórmulas próprias.

**Calendário de exames.** Cada coordenação marca a data, a hora, a sala e o júri dos exames das suas disciplinas, mas cada turma faz exames de várias coordenações. Hoje um grupo propõe datas para disciplinas de outros grupos, que ficam «a confirmar», e os choques de turma ou de sala só se descobrem depois.

Os dois processos têm problemas comuns a todas as coordenações:

- **Várias versões**: o mesmo DSD ou calendário circula em várias cópias e não se sabe qual é a válida.
- **Dados repetidos e incoerentes**: docentes, disciplinas, turmas e salas são escritos à mão em cada ficheiro, com grafias e valores diferentes.
- **Resumos desatualizados**: os quadros-resumo e os totais não acompanham as alterações.
- **Coordenação fora dos ficheiros**: os pedidos de docentes e as confirmações de datas entre coordenações fazem-se por correio ou de viva voz, sem estado nem histórico.
- **Visão parcial**: ninguém vê a carga total de um docente que leciona em vários cursos, nem todos os exames de uma turma, nem o DSD completo de um curso, cujas disciplinas são atribuídas por várias coordenações.
- **Trabalho manual**: as horas calculam-se à mão, com fórmulas que variam de ficheiro para ficheiro, e os conflitos de datas e salas verificam-se a olho.
- **Sem rastreabilidade**: não fica registado quem alterou o quê, nem porquê.

## Objetivos

**Objetivo geral:** dar às coordenações da Universidade uma plataforma única, consistente e rastreável, a PGC, onde se elaboram, validam e publicam o DSD e o calendário de exames de cada ano letivo, sobre os mesmos dados de base.

**Objetivos específicos – núcleo partilhado:**

- Registar uma só vez cursos, planos de estudos, disciplinas, docentes, salas, matrículas e inscritos, cada dado introduzido por quem é responsável por ele (o gestor da PGC, os Serviços Académicos e o Património) e, sempre que possível, importado do SII.
- Mostrar a cada coordenador as salas existentes, por tipo e capacidade, e a dimensão das turmas. Dar a cada coordenador, que é também o diretor de curso, a visão completa de cada curso, com o DSD e o calendário de exames de todas as coordenações que lhe dão aulas.
- Guardar o histórico de alterações e as versões de cada módulo, incluindo as alterações feitas depois do fecho ou da publicação.

**Objetivos específicos – módulo DSD:**

- Permitir a cada coordenação atribuir docentes às disciplinas da sua área, em todos os cursos, por tipo de aula, juntando ou dividindo turmas.
- Calcular automaticamente a carga letiva anual de cada docente e o seu estado face ao intervalo de horas letivas que lhe corresponde.
- Gerir as propostas de disciplinas a concurso, sempre justificadas, que o Conselho Executivo da Faculdade aprova ou recusa, com aviso por correio eletrónico, e registar o docente que daí resulta.
- Detetar disciplinas sem docente, cargas fora do intervalo e dados inconsistentes antes de o Conselho Executivo fechar o DSD de cada coordenação.
- Dar a quem faz os horários a informação de que precisa e produzir os mapas e relatórios que hoje se fazem à mão, com exportação para Excel e PDF.

**Objetivos específicos – módulo calendário de exames:**

- Marcar num calendário único, partilhado pelas coordenações, os exames de 1.ª chamada, 2.ª chamada e recurso, sem conflitos de turma, sala ou júri.
- Publicar o calendário para toda a Universidade e exportá-lo em Word e PDF no formato usado hoje.

## Âmbito

O projeto constrói a PGC, com o núcleo partilhado e os módulos DSD e calendário de exames, para todas as coordenações da Universidade, em todas as Faculdades. No DSD, cobre o ciclo completo de cada ano letivo, da preparação ao fecho; no calendário de exames, as três épocas de cada semestre, da marcação à publicação.

**Incluído – núcleo partilhado**

- Cadastros feitos pelo gestor da PGC: cursos (licenciatura, mestrado e doutoramento), planos de estudos, disciplinas com carga semestral e semanal e horas por tipo de aula, disciplinas transversais, docentes com categoria, coordenação e cargos, intervalos de horas por categoria e por cargo, épocas e faixas horárias dos exames e contas de utilizador.
- Matrículas por curso e inscritos por disciplina (Serviços Académicos, de preferência a partir do SII) e as salas da Universidade, com localização, nome (quando tiver), tipo e capacidade (Património).
- Utilizadores, perfis e permissões; notificações por correio eletrónico; integração com o SII; exportação para Excel, Word e PDF; histórico e versões.

**Incluído – módulo DSD**

- Turmas e grupos, com junção de turmas nas disciplinas transversais e divisão em grupos.
- Atribuição de docentes a disciplinas, turmas e tipos de aula, um docente por tipo de aula e, quando necessário, com partilha, e outras atividades da componente não letiva.
- Propostas justificadas de disciplinas a concurso, decisão do Conselho Executivo e registo do docente contratado ou selecionado.
- Calendário do DSD (abertura, prazos e fecho), cálculo de cargas e validações, relatórios, fecho pelo Conselho Executivo, alterações posteriores ao fecho e cópia a partir de um ano anterior.
- Consulta para quem faz os horários e, para cada docente, da sua própria distribuição.

**Incluído – módulo calendário de exames**

- Marcação dos exames de 1.ª chamada, 2.ª chamada e recurso, com junção de turmas, divisão em grupos, faixa horária, salas, docente responsável e júri.
- Verificação de conflitos de turma, sala e júri; avisos entre coordenações; cópia a partir de um ano anterior.
- Publicação para toda a Universidade e exportação em Word e PDF.

**Fora do âmbito (primeira fase)**

- Construção de horários (dias, horas e salas das aulas): fica para o módulo de horários, a fase seguinte da PGC; este projeto prepara os dados e a arquitetura para ele.
- O processo de concurso docente e de contratação: o sistema regista a proposta, a decisão e o resultado, não o processo.
- Processamento salarial, contratos e avaliação de desempenho.
- Gestão de notas, sumários e pautas.
- Levantamento do software dos laboratórios, que hoje segue um circuito próprio.

## A PGC e os seus módulos

A PGC constrói-se sobre um núcleo de dados partilhado. O DSD e o calendário de exames são os seus primeiros módulos; os horários e outras ferramentas das coordenações entram depois como novos módulos sobre os mesmos dados. Cada módulo responde a uma pergunta e entrega o resultado ao seguinte, sem voltar a introduzir dados.

| Módulo | Pergunta a que responde | Usa | Produz | Quando |
| --- | --- | --- | --- | --- |
| Núcleo partilhado | — | Dados do gestor da PGC, dos Serviços Académicos, do Património e do SII | Cursos, disciplinas, docentes, turmas e grupos, salas, utilizadores e calendário letivo | Este projeto |
| DSD | Quem ensina o quê, a quem e quantas horas? | Núcleo | DSD fechado de cada coordenação, com o tipo e a capacidade de sala de cada turma ou grupo | Este projeto |
| Calendário de exames | Quando, em que sala e com que júri é cada exame? | Núcleo e, para o docente responsável, o DSD | Calendário de exames de 1.ª chamada, 2.ª chamada e recurso, por turma e por coordenação | Este projeto (fase 2) |
| Horários | Quando e onde é cada aula? | DSD fechado, salas, disponibilidade dos docentes | Horário por turma, por docente e por sala | Fase seguinte |
| Consulta e publicação | Onde e quando é a minha aula? | Horários | Horários visíveis para docentes e estudantes; exportação para o SII | Fase seguinte |

O módulo de horários, a especificar num projeto próprio, deverá incluir: a grelha de tempos de cada Faculdade, a disponibilidade e as restrições dos docentes, a atribuição de salas por tipo e capacidade, a deteção de conflitos (o mesmo docente, turma ou sala em dois sítios à mesma hora), ajustes manuais e os pedidos de troca de horário.

Gerar um horário sem conflitos é um problema de otimização com restrições, que não se resolve com formulários. Antes de construir um motor próprio, a plataforma deve integrar uma ferramenta livre já usada em universidades (FET ou UniTime): exporta o DSD fechado, gera o horário nessa ferramenta e importa-o de volta. Um motor próprio, com Google OR-Tools, fica como segunda opção se essas ferramentas não cobrirem as regras da Uni-CV.

Para que o módulo de horários encaixe sem retrabalho, este projeto já garante seis coisas:

- o núcleo partilhado é independente do DSD e pode ser usado por qualquer módulo;
- o núcleo inclui desde já o tempo: calendário letivo, grelha de franjas horárias de cada Faculdade, disponibilidade dos docentes e salas partilhadas entre Faculdades;
- o DSD fechado regista, para cada turma ou grupo, o tipo de aula, as horas semanais, o docente e o tipo e a capacidade de sala necessários, que são exatamente a procura que os horários têm de satisfazer;
- a fila de tarefas e o contentor próprio para o motor de horários ficam previstos na arquitetura;
- os perfis e as permissões preveem novos perfis, como quem faz os horários ou os estudantes;
- o DSD, o calendário de exames e os horários partilham a mesma base de dados, sem exportações entre eles.

