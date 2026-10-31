# Dados fictícios para desenvolvimento

O repositório **nunca** contém dados reais de docentes nem de estudantes (nomes, contactos, cargas reais, listas do SII). Os ficheiros Excel/Word atuais só se usam no piloto, fora do repositório, para comparar cargas.

## O que os dados fictícios devem cobrir

Um conjunto pequeno, carregável com um comando, que permita testar todas as regras:

- 2 Faculdades; 3 a 4 coordenações (uma delas com disciplinas em vários cursos).
- 3 cursos de licenciatura e 1 de mestrado, com planos de 2 anos e 2 semestres cada.
- Um curso com **duas turmas no mesmo ano** (para testar o caso futuro), os restantes com uma.
- Pelo menos uma **disciplina transversal** declarada em 2 cursos e recusada num 3.º.
- Docentes de cada categoria, alguns com cargos, para cobrir os quatro estados de carga (abaixo da mínima, no intervalo, na máxima, acima da máxima).
- Um tipo de aula partilhado entre dois docentes (50%/50%).
- Salas de vários tipos e capacidades, incluindo uma pequena demais para um exame.
- Uma época de exames com faixas horárias e alguns exames já marcados por outra coordenação na mesma turma.
- Listas de inscritos fictícias, incluindo um exame sem inscritos.

## Nomes

Usar nomes claramente fictícios («Docente A», «Curso X», «Coordenação de Teste 1») ou gerados (Faker, locale `pt_PT`). Os valores dos intervalos de horas são de teste e não representam valores reais da Uni-CV.
