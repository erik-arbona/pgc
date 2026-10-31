# Registo de decisões da PGC

Decisões tomadas durante a especificação. Prevalecem sobre qualquer outro texto se houver conflito. Cada decisão nova acrescenta-se no fim, com data.

## Até 31/10/2026 (especificação inicial)

### Plataforma e âmbito
- D01. O sistema chama-se **PGC – Plataforma de Gestão das Coordenações**. DSD e calendário de exames são módulos ao mesmo nível; os horários vêm depois.
- D02. Abrange todas as coordenações e Faculdades da Uni-CV; piloto com um grupo de Faculdades, em paralelo com os ficheiros atuais.
- D03. Não se importam os DSD nem os calendários atuais (Excel/Word): os dados introduzem-se limpos. Os Excel servem só para comparar no piloto.
- D04. O sistema permite começar um ano letivo a partir de uma cópia editável do DSD e do calendário de um ano anterior.
- D05. Promotor e autor dos materiais: ICUB.

### Perfis
- D06. Existe o perfil **Gestor da PGC** (um por Faculdade ou para várias): docentes, cargos, planos, disciplinas, disciplinas transversais, intervalos, épocas e faixas de exames, contas; regista o docente obtido por concurso.
- D07. O **Património** introduz as salas (localização, nome quando tiver, tipo, capacidade) e não atribui salas.
- D08. O coordenador só atribui docentes da sua coordenação.
- D09. Os docentes consultam, só em leitura, a sua própria distribuição, já durante a preparação.
- D10. O **coordenador é também o diretor de curso**: não há perfil próprio de diretor de curso. Na vista por curso vê em leitura o que é de outras coordenações, sem as listas de estudantes desses exames.

### DSD
- D11. Intervalos de horas letivas (mínimo e máximo) por **categoria** e por **cargo**, definidos pelo gestor da PGC; quando há vários, aplica-se o do **máximo mais baixo**.
- D12. O intervalo mede-se em **horas letivas semanais somadas dos dois semestres**; valida **só as horas letivas**.
- D13. **Horas extra** = total de horas letivas − máximo do intervalo; só com aceitação do docente; **registadas pelo coordenador**.
- D14. **Preparação** = T + (TP + P + L) × 1,5, como parâmetro configurável.
- D15. **Componente não letiva** (complementos de ensino, investigação, gestão e serviços) introduzida pelo coordenador, caso a caso, com descrição e horas, por semestre.
- D16. Abaixo da mínima, o coordenador regista o motivo; o CE pode recusá-lo.
- D17. Quando não pode atribuir, o coordenador propõe a concurso com justificação obrigatória; o CE aprova (colaborador ou concurso) ou recusa.
- D18. ~~O CE fecha o DSD de cada coordenação; depois do fecho, gestor da PGC e CE podem alterar, criando nova versão.~~ Substituída por D43: fecha o gestor da PGC; depois do fecho só ele altera, criando nova versão.
- D19. **Um docente por tipo de aula** de cada turma ou grupo (p. ex. teórica e práticas com docentes diferentes). A partilha do mesmo tipo de aula com percentagem é opcional e excecional.
- D20. A interface do DSD **não imita o Excel**: vistas por tarefa (visão geral, ficha do docente, atribuição por disciplina, vista por curso).

### Turmas e junções
- D21. Hoje há **uma turma por curso e ano**; o modelo admite **várias turmas por curso e ano** desde o início, sem mudar nada no caso atual.
- D22. **Disciplinas transversais**: o gestor declara-as e indica **em que cursos** cada uma é transversal. Só se juntam turmas desses cursos, no mesmo semestre. Vale para o DSD e para os exames.
- D23. Turmas do mesmo curso (quando houver várias) podem ser juntas pelo coordenador; no futuro também por quem faz os horários.

### Calendário de exames
- D24. Calendário único partilhado entre coordenações; o gestor da PGC define as épocas (datas) e as faixas horárias.
- D25. O coordenador marca os exames das suas disciplinas: junta turmas (regras de D22), divide em grupos, escolhe dia, faixa e salas; responsável vindo do DSD (alterável); júri escolhido entre os docentes da coordenação.
- D26. Regras sempre verificadas no servidor: uma turma não tem dois exames no mesmo dia; uma sala não tem dois exames à mesma hora.
- D27. Avisos por correio eletrónico quando outra coordenação altera um exame numa turma comum.
- D28. O calendário publicado é visível para todos os utilizadores da Universidade (vista pública em cache, já na fase 2).
- D29. Listas de estudantes por exame chegam do SII em cada semestre (substituem o Excel atual); visíveis só para a coordenação, o responsável e o júri.
- D30. Exames sem inscritos ficam assinalados (outra cor) e podem ser retirados.
- D31. Só se aceitam salas com capacidade ≥ inscritos (do exame ou de cada grupo); turmas juntas somam inscritos; a soma dos grupos tem de igualar o total; a capacidade aparece sempre nas sugestões; se a lista muda e a sala deixa de chegar, o exame fica assinalado antes de publicar.

### Vista por curso
- D32. DSD e exames filtráveis por curso (disciplinas, docentes, turmas, grupos, tipos de aula), reunindo todas as coordenações; disciplinas transversais marcadas como partilhadas e contadas uma vez nos totais gerais.

### Técnica e recursos
- D33. Monólito modular em Django + PostgreSQL + HTMX + Celery/Redis; publicação em cache e iCal.
- D34. Horários: integrar primeiro FET ou UniTime; motor próprio com OR-Tools só se necessário.
- D35. Desenvolvimento com programação assistida por agentes, só com o plano Pro de Claude; computador novo com 16 GB de RAM (a adquirir).
- D36. Todo o código e todos os comentários (docstrings, nomes de testes, mensagens de commit) em inglês; interface e documentação em `docs/` em português europeu.
- D37. O código tem de estar bem documentado: docstrings em módulos, classes e funções públicas com referência à especificação e às decisões, type hints, `help_text` nos modelos e comentários que expliquem o porquê (regras em `CLAUDE.md`).
- D38. Modelo de utilizador próprio (`core.User`) desde a primeira migração. Um utilizador tem várias atribuições (perfil + âmbito); o âmbito é um tipo (Faculdade, coordenação, docente, nenhum) mais um identificador numérico, sem chave estrangeira até existirem as entidades (T2.1, T3.1). Só coordenador (coordenação), Conselho Executivo e gestor da PGC (Faculdade) e docente (o próprio) têm tipo de âmbito fixado; para consulta, Serviços Académicos e Património a especificação não o define e qualquer tipo é aceite até se decidir.
- D39. Permissões verificadas no servidor por um registo de ações (`core.permissions`): cada ação lista os perfis que a podem fazer e se escreve; consulta e docente nunca recebem ações de escrita; ação desconhecida falha fechada; o `is_superuser` do Django não dá acesso de negócio; as ações com âmbito (`scoped=True`) nunca passam «para qualquer âmbito»: verificá-las sem indicar o âmbito falha com `ImproperlyConfigured`; o âmbito compara-se por igualdade exata (a hierarquia Faculdade › coordenação entra com T2.1). A especificação não tem uma matriz completa perfil × ação: cada funcionalidade regista as suas ações quando for construída.
- D40. Auditoria (`core.AuditEntry`): só se acrescenta, nunca se altera nem apaga (pelo ORM); escreve-se na mesma transação que a alteração, através de `audited_save` e `audited_delete`. O motivo é obrigatório em alteração e eliminação e opcional na criação (a especificação pede o motivo mas não diz quando é obrigatório; **decisão a confirmar**).
- D41. Autenticação por fornecedor de identidade configurável (`AUTH_IDENTITY_PROVIDER`): o fornecedor só identifica; perfis e âmbitos vêm sempre das atribuições. Enquanto a questão em aberto (LDAP/AD ou SSO) não tiver resposta, só existe o fornecedor local (utilizador e palavra-passe), aceite apenas com `DEBUG` ligado ou com `ALLOW_LOCAL_LOGIN` definido de propósito; caso contrário o arranque falha (`core.E002`), para não ficar em produção uma palavra-passe nova contra o que a especificação pede (**decisão a confirmar**).
- D42. Estrutura académica (`academic`): uma coordenação pertence a uma só Faculdade; o ano letivo guarda apenas o ano de início (o rótulo «2026/2027» deriva-se dele; datas e semestres não constam da especificação); unicidade do código da Faculdade, do nome da coordenação por Faculdade e de Faculdade + nome + grau do curso, por integridade (**pressupostos a confirmar**). Eliminar uma Faculdade com coordenações ou cursos é bloqueado.

## 31/10/2026 (ajuste pedido pelo utilizador)

- D43. Ciclo de vida do DSD, substitui D18. O **gestor da PGC cria** o DSD de cada ano letivo, com os dois semestres, e **abre e fecha cada semestre**, um ou os dois, para todas as coordenações ou para uma só; pode reabrir. Com o semestre aberto para a sua coordenação, o **coordenador preenche e altera** o DSD; fechado, só lê. O coordenador **não cria nem elimina** DSD. Depois do fecho só o gestor da PGC altera, criando nova versão com data, autor e motivo. O **Conselho Executivo** mantém a aprovação ou recusa de concursos e justificações de carga abaixo da mínima (D16, D17) e os relatórios, mas já não fecha nem altera o DSD. Pendente de rever no mesmo espírito: `03_requisitos_funcionais.md` (bloco de fecho e versões) quando se implementar o módulo DSD (fase 2).
- D44. Plano de estudos e disciplina (`academic`): o plano de estudos tem versões por ano letivo (curso + ano letivo de início, único); a disciplina tem código único por plano, ECTS, ano curricular, semestre (1 ou 2), coordenação responsável e uma carga semestral total; a carga semanal guarda-se por tipo de aula (`SubjectClassLoad`) e o total semanal calcula-se por soma; o tipo de aula existe só como tabela mínima (T2.3 completa). Confirmado pelo utilizador: a carga semestral é um total por disciplina e a carga semanal da disciplina reparte-se por tipo de aula (p. ex. 75 h no semestre, 5 h semanais = 3 T + 2 P). **Pressupostos a confirmar**: o código é único dentro do plano; ECTS e horas com duas casas decimais. Sem regra de mesma Faculdade entre curso e coordenação, porque a especificação não a prevê.
