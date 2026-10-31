# PGC – Módulo calendário de exames

> Parte da especificação da PGC (Plataforma de Gestão das Coordenações – Uni-CV). Fonte: documento do projeto, versão de 31/10/2026.

## Módulo calendário de exames

O calendário de exames é um módulo da PGC que usa o núcleo partilhado (disciplinas, turmas, salas e calendário letivo) e, para o docente responsável, o DSD. Cobre as três épocas de exames: 1.ª chamada, 2.ª chamada e recurso.

**Como funciona:**

- O gestor da PGC introduz, para cada semestre e cada época (1.ª chamada, 2.ª chamada e recurso), as datas de início e de fim dos exames, a partir do calendário académico, e as faixas horárias em que os exames se podem marcar.
- Há um só calendário, partilhado por todas as coordenações. Cada coordenação marca os exames das disciplinas da sua área e vê, para as mesmas turmas, os exames já marcados pelas outras. Isto substitui a troca de ficheiros entre grupos disciplinares, em que um grupo propõe datas para disciplinas de outro e fica tudo «a confirmar».
- Para o exame de cada disciplina, o coordenador:
  - junta turmas de cursos diferentes quando a disciplina é transversal, e apenas entre os cursos indicados pelo gestor da PGC (por exemplo, um único exame de Introdução à Programação para EIC, EE, Matemática, EGI, EQB, EM e EC); o número de inscritos do exame passa a ser a soma dos inscritos dessas turmas;
  - divide o exame em grupos, indicando quantos estudantes vai ter cada grupo; a soma dos grupos tem de ser igual ao total de inscritos, e o sistema não aceita a divisão enquanto não for; cada grupo tem a sua sala e, se for preciso, a sua hora;
  - escolhe o dia, dentro da época, e uma das faixas horárias definidas pelo gestor da PGC (por exemplo, 09:00-11:00, 11:30-13:30 e 14:00-16:00), vendo os dias já ocupados de cada turma;
  - atribui a sala ou as salas, escolhendo apenas entre as salas livres a essa hora com capacidade para os inscritos do exame ou do grupo; o sistema mostra sempre a capacidade de cada sala sugerida, ao lado do número de estudantes que tem de acolher.
- O docente responsável pelo exame é, por defeito, o docente da disciplina no DSD; o coordenador pode indicar outro quando esse docente não pode estar presente (ausência, licença, etc.).
- O júri é escolhido pelo coordenador entre os docentes da sua coordenação, com um ou mais membros.
- Em cada semestre, o SII entrega à PGC, para cada exame (disciplina e época), a lista dos estudantes inscritos. Esta lista substitui o ficheiro Excel que hoje chega às coordenações: o coordenador consulta-a na PGC, exame a exame. O número de inscritos de cada exame (ou de cada grupo, quando o exame se divide) determina as salas possíveis: o sistema só deixa escolher salas livres com capacidade igual ou superior a esse número. Se nenhuma sala livre comportar todos os inscritos, o coordenador tem de dividir o exame em grupos, e cada grupo só pode ficar numa sala que o comporte.
- Regras que o sistema verifica sempre no servidor: uma turma não tem dois exames no mesmo dia; uma sala não tem dois exames à mesma hora, mesmo de coordenações diferentes; só se aceita uma sala com capacidade igual ou superior ao número de inscritos do exame ou do grupo, segundo a lista do SII. O sistema avisa também quando um docente fica em dois júris à mesma hora.
- O coordenador pode partir de uma cópia do calendário da mesma época de um ano anterior: a cópia traz as disciplinas, as junções, as horas, as salas e o júri, coloca cada exame no dia equivalente da nova época e fica editável; o sistema volta a verificar todas as regras e assinala os conflitos.
- O calendário pode ser consultado, só em leitura, por todos os utilizadores da Universidade, numa vista pública servida em cache (a camada de publicação prevista para os horários, antecipada para a fase 2), e exportado em Word e PDF no formato usado hoje: por época, curso e ano, com disciplina, n.º de inscritos, data, hora, sala e júri.
- Quando outra coordenação marca, altera ou anula um exame numa turma em que a coordenação também tem disciplinas, o coordenador recebe um aviso por correio eletrónico.
- Se o calendário já estiver marcado e a lista do SII mostrar que um exame não tem estudantes inscritos, o sistema assinala esse exame com outra cor e o coordenador pode retirá-lo do calendário, libertando o dia da turma e a sala. Quando a lista muda (novos inscritos ou desistências), o número de inscritos atualiza-se; se uma sala já marcada deixar de comportar os inscritos, o exame fica assinalado e o coordenador tem de escolher outra sala ou dividir o exame em grupos antes da publicação.

**Concorrência:** como duas coordenações podem tentar marcar o mesmo dia para a mesma turma ao mesmo tempo, a base de dados garante que só existe um exame por turma, época e dia, e um exame por sala, data e hora; a segunda marcação é recusada com uma mensagem clara e o calendário atualiza-se.

**Dados:** cada exame liga uma disciplina, uma época, uma ou mais turmas (de um ou mais cursos), um docente responsável e um júri; tem a lista de estudantes inscritos vinda do SII; tem um ou mais grupos, cada um com data, hora, sala e número de inscritos; e regista quem o marcou e quando.

