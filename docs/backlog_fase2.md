# Backlog – Fase 2 · Núcleo do DSD

Fase 2 da especificação: **turmas, grupos, atribuição, carga, alertas e calendário de exames** (blocos 3, 4, 6 e 10; `03_requisitos_funcionais.md`, `08_plano.md`). Termina na **Porta 1**: a carga calculada coincide com os ficheiros Excel.

Cada tarefa cabe numa sessão; marcar `[x]` com testes a passar e código documentado (`CLAUDE.md`). ⚑ = toca uma questão em aberto (ver «Questões» no fim).

**Fora desta fase (fase 3):** propostas de concurso e convite (bloco 5), fecho com versões, alteração depois do fecho, comparação e cópia do ano anterior (bloco 7), calendário do DSD, notificações e exportação para o SII (bloco 9). Do bloco 7 entra já só a abertura e o fecho do semestre (T2.2), porque sem isso o D43 não funciona.

## 0. Preparação (ajustes à fase 1)
- [x] T0.1 Corrigir o glossário e o bloco 7 de `03` ao D43 (fecha o gestor da PGC, não o CE); acrescentar ao glossário «unidade letiva» (`TeachingUnit`).
- [x] T0.2 Ligação curso → coordenação responsável, da mesma Faculdade (D10, D44). ⚑ Q2
- [x] T0.3 Referência opaca do SII em curso e disciplina, editável pelo gestor (D66).
- [x] T0.4 Verificação de âmbito por coordenação reutilizável: coordenador (própria), CE e gestor (Faculdade da coordenação), docente (o próprio) (D39, D51, D09).
- [ ] T0.6 Percursos de um curso (D75, D79), em três partes:
  - [x] T0.6a Modelo e regras: `Track` por plano, `Subject.track` e `ClassGroup.track` opcionais, validações, ano curricular da turma, disciplinas que cada turma vê, `create_class_group` com percurso.
  - [x] T0.6b Ecrãs: gerir percursos, escolher o percurso na disciplina e na turma, colunas nas listas.
  - [x] T0.6c Carregar os planos reais de EIC e TM (D78), comando `load_real_plans` (D80). Q26 a Q28 seguem com os valores por defeito de D80, por confirmar.
- [ ] T0.5 Proteções de apagamento: turma com atribuições (D54), sala com exames (D63), docente com atribuições. **Em curso**: a turma e o docente com unidades já estão protegidos (FK `PROTECT`, testes em T5.1a); falta a sala com exames, com T7.2.

## 1. Matrículas e inscritos (bloco 3)
- [x] T1.1 Modelo de matrículas **por turma** e ano letivo, estimadas e atualizadas com as reais, sem nomes (D66, D76, D81).
- [ ] T1.2 Importação pela `SiiSource` (CSV ou consulta à base do SII), com mapeamento de referências, relatório sem valores e auditoria. **Aplazada** até haver acesso ao SII (D82, Q4); o contrato aceitará a coluna opcional do percurso, porque os estudantes escolhem o percurso e o número tem de vir do SII ou ser introduzido.
- [x] T1.3 Introdução e correção manual da matrícula (estimada e depois real) de cada turma pelos Serviços Académicos, com lista das turmas que existem num ano e ainda não têm número (D83).
- [ ] T1.4 Inscritos por disciplina e época (importação; visibilidade D29). **Aplazada** até haver acesso ao SII e o módulo de exames (D84, Q4): são listas com nomes e nada do DSD as precisa.
- [x] T1.5 Dimensão de cada turma, consultável pelo coordenador (`02`), só em leitura (D84).

## 2. DSD e ofertas (D43, `04`)
- [x] T2.1 DSD por ano letivo com os dois semestres, criado só pelo gestor; o coordenador não cria nem elimina (D43). Um só DSD por ano letivo, garantido na BD: se outro gestor tentar criar um segundo, é recusado com mensagem clara, mesmo em simultâneo.
- [x] T2.2 Abertura, fecho e reabertura por semestre e coordenação, para uma ou todas; estado imposto em todas as escritas (D43).
- [x] T2.3 Geração das ofertas do semestre a partir das turmas ativas e do plano de cada turma (D48, D49), com regente (`Offering.lead_teacher`).
  - [x] T2.3a Gerar as ofertas e as turmas de cada uma; lista por semestre e coordenação (D87).
  - [x] T2.3b Regente (`lead_teacher`): quem o define, só docentes da coordenação da disciplina.

## 3. Unidades letivas: junções e grupos (bloco 3)
- [x] T3.1 Unidade letiva = oferta × tipo de aula × público (turmas juntas ou um grupo); por defeito uma por turma; bloqueio otimista.
  - [x] T3.1a Modelos `TeachingUnit` e `TeachingUnitMember`; criação das unidades por defeito ao gerar as ofertas; obsoletas contadas (D89).
  - [x] T3.1b Página só de leitura de cada oferta com as suas unidades.
- [x] T3.2 Divisão em N grupos por tipo de aula (`SubGroup`). ~~⚑ Q6, Q7~~ (D90)
  - [x] T3.2a Modelo `SubGroup`, público da unidade com turmas ou grupos, operação «definir o número de grupos», gerador e obsoletas.
  - [x] T3.2b Formulário e botões na página da oferta.
- [x] T3.3 Junção de turmas do mesmo curso por tipo de aula (D23).
  - [x] T3.3a Juntar e separar (serviço): regra da sala por quantidades, pedido de sala na unidade, tamanho dos grupos (D91).
  - [x] T3.3b Casillas e «Juntar selecionadas», página de confirmação, «Separar»; botão «Alterar n.º de grupos» num grupo juntado.
- [x] T3.4 Junção entre cursos: só transversais, só cursos indicados, mesmo semestre (bloqueia); aviso de carga diferente (D22, D47, D48). ⚑ Q8
  - [x] T3.4a Serviço: juntar membros de ofertas diferentes entre disciplinas transversais, aviso e confirmação da carga diferente, obsoletas por membro, separar para a oferta própria (D92).
  - [x] T3.4b Ecrãs: secção «Outros cursos», escolha da anfitriã e confirmação da carga, «Juntada em», botão de grupos de uma turma de outro curso.
- [x] T3.5 Tipo e capacidade de sala pedidos por turma ou grupo; aviso se nenhuma sala serve (`room_summary`, bloco 8, D64). ⚑ Q9

## 4. Regras de cálculo (módulo de domínio puro, bloco 6)
- [x] T4.1 Horas letivas por semestre: junção conta uma vez, grupos N vezes, quota (`05`). Testes exaustivos.
- [x] T4.2 Preparação por docente com os pesos (D14, D61). ⚑ Q10
- [x] T4.3 Total anual = soma dos semestres; intervalo por `resolve_load_range` com data de referência (D12, D58). ⚑ Q11
- [x] T4.4 Quatro estados mais «sem intervalo»; mínimo opcional (D46, D58); horas extra = total − máximo (D13).
- [ ] T4.5 Alertas: unidade sem docente, quotas ≠ 100%, sem sala pedida, fora do intervalo (`05`).

## 5. Atribuição (bloco 4)
- [x] T5.1 Um docente por unidade letiva, só da coordenação da disciplina (D08, D19); bloqueio otimista e restrição na BD.
  - [x] T5.1a Serviço: `assign_teacher` / `unassign_teacher`, permissão, regras de junção, separação e divisão (D94).
  - [x] T5.1b Cálculo ao vivo (adaptador para as regras puras) e ecrãs: coluna «Docente», formulário para dar, mudar e retirar.
- ~~T5.2 Partilha com quota~~ **Cancelada** (D94): uma unidade tem um só docente e não há quotas.
- [x] T5.3 Componente não letiva por docente e semestre: tipo, descrição e horas (D15).
- [x] T5.4 Horas extra aceites, registadas pelo coordenador (D13). ⚑ Q13
- [x] T5.5 Motivo abaixo da mínima (coordenador); aceitação ou recusa pelo CE, que devolve o caso (D16, bloco 6). ⚑ Q14

## 6. Vistas (D20, `07`)
- [x] T6.1 Visão geral da coordenação: pendentes e barra de carga com estado em cor e texto.
- [x] T6.2 Atribuição por disciplina (HTMX, D50).
- [x] T6.3 Ficha do docente; leitura pelo próprio docente (D09).
- [x] T6.4 Comparação com o Excel: exportação CSV da carga por docente, para a Porta 1.

## 6b. Interface visual (D20, D50)
As secções 0 a 6 construíram as regras e os ecrãs com um estilo mínimo (D50). Esta secção trata do aspeto e da navegação, que ainda não estão desenhados. ⚑ Q29
- [ ] T6.5 Desenho: página inicial por perfil, menu, estilos comuns (cores, tipografia, tabelas, formulários, estados e mensagens) e acessibilidade; a partir de uma referência do utilizador.
- [ ] T6.6 Aplicar o desenho aos ecrãs existentes (dados mestres, DSD, ofertas, ficha do docente, visão geral da coordenação) sem alterar regras nem permissões.

## 7. Calendário de exames (bloco 10)
- [ ] T7.1 Épocas por semestre (datas) e faixas horárias, pelo gestor (D24). ⚑ Q15
- [ ] T7.2 Exame: disciplina, época, turmas juntas (regras D22), responsável vindo do regente (alterável), júri da coordenação (D25). ⚑ Q16, Q17
- [ ] T7.3 Restrições na BD: um exame por turma, época e dia; uma sala por data e faixa (D26); recusa clara na concorrência.
- [ ] T7.4 Grupos do exame: soma = inscritos; capacidade ≥ inscritos; sugestões com capacidade (D31).
- [ ] T7.5 Dias ocupados por turma; aviso de júri em dois exames à mesma hora (`06`).
- [ ] T7.6 Exames sem inscritos assinalados e retiráveis; sala que deixa de chegar assinalada (D30, D31). ⚑ Q18
- [ ] T7.7 Aviso por correio a outras coordenações da turma comum (D27; Celery + SMTP).
- [ ] T7.8 Vista por curso, ano e turma; listas visíveis só para coordenação, responsável e júri (D29).
- [ ] T7.9 Publicação em cache e iCal (D28). ⚑ Q19
- [ ] T7.10 Cópia da época de um ano anterior, com nova verificação (D04). ⚑ Q20
- [ ] T7.11 Exportação Word e PDF por turma, curso e coordenação.

## 8. Dados fictícios
- [ ] T8.1 Completar `load_demo_data`: quatro estados de carga, partilha 50/50, época com exames de outra coordenação, exame sem inscritos (D65).

## Ordem de construção recomendada
1. Secção 0 (T0.2 e T0.4 definem os âmbitos de que dependem todas as escritas).
2. Secção 4 assim que os modelos de 2 e 3 estiverem esboçados: é um módulo puro, constrói-se com testes primeiro, e a Porta 1 depende dele.
3. Secções 1 → 2 → 3 → 5.
4. Secção 6, para comparar com o Excel.
5. Secção 7, que pode correr em paralelo com a 6.
6. Secção 8 no fim.

## Tarefas de maior risco (pedem revisão independente)
- **T4.1–T4.4** motor de cálculo: junção uma vez, grupos N vezes, quotas, preparação, soma anual e limites exatos dos estados (decimais). Testes por tabela e de propriedades.
- **T5.1–T5.2** atribuição com concorrência: um docente por unidade, quotas = 100%, bloqueio otimista e `select_for_update`.
- **T7.3–T7.4** restrições de exames na BD e capacidade face a listas que mudam.
- **T2.2 e T0.4** ciclo de vida e permissões: todas as escritas respeitam aberto/fechado, âmbito, CE que só decide, docente que só lê o seu, privacidade das listas (D29).
- **Cópia da época (T7.10)**: não pode tocar no ano anterior.

## Questões que bloqueiam ou tocam tarefas (proposta por defeito)
- **Q2** (T0.2): preciso do vínculo curso → coordenação nesta fase? *Defeito:* sim.
- ~~**Q3** (T1.1, T1.5): como se sabe a dimensão de cada turma A/B?~~ Resolvida: os Serviços Académicos introduzem o número **por turma** (D81).
- **Q4** (T1.2, T1.4): que dados dá o SII, por que meio e quando (D66, em aberto). *Defeito:* só CSV.
- ~~**Q5** (T2.1): um DSD por ano letivo para toda a Universidade ou um por Faculdade?~~ Resolvida: um por ano letivo, criado pelo gestor, aberto e fechado por coordenação (D43).
- ~~**Q6** (T3.2): mínimo e máximo de alunos por tipo de aula~~ Resolvida por defeito: sem regra e sem guardar a dimensão do grupo (D90).
- ~~**Q7** (T3.2): um grupo pode misturar alunos de turmas juntas?~~ Resolvida: sim, os grupos podem juntar-se entre turmas e cursos (transversais), em T3.3 e T3.4 (D90).
- ~~**Q8** (T3.4): junção com horas ou coordenações diferentes~~ Resolvida por defeito: contam as horas da disciplina anfitriã (escolhida pelo coordenador) com aviso e confirmação; coordenações diferentes não se juntam (D92).
- ~~**Q9** (T3.5): a sala pede-se por turma/grupo ou por unidade letiva?~~ Resolvida por defeito: por unidade letiva; aviso e não bloqueio, salvo ao juntar (D93).
- ~~**Q10** (T4.2): a preparação conta por repetição (N grupos) e pesa-se pela quota?~~ Resolvida: acompanha cada hora letiva, repetida por grupo e pela quota (D71); confirmar na Porta 1.
- **Q11** (T4.3, fecho): a função recebe a data de referência (D72); aberto usa hoje, fechado conserva a data de fecho. *Por decidir:* a data quando só um semestre está fechado.
- ~~**Q12** (T5.2): as quotas somam exatamente 100% ao guardar ou é só aviso?~~ Já não se aplica: não há quotas (D94).
- **Q13** (T5.4): horas extra aceites por docente e ano ou por atribuição? *Defeito:* por docente e ano, com nº de horas.
- **Q14** (T5.5): como se avisa o coordenador de uma recusa sem o bloco 9? *Defeito:* só aviso na aplicação.
- **Q15** (T7.1): as faixas horárias podem sobrepor-se? *Defeito:* não.
- **Q16** (T7.2): várias turmas do mesmo ano: um exame ou um por turma? *Defeito:* um por turma, que o coordenador pode juntar.
- **Q17** (T7.2): num exame conjunto com regentes ou coordenações diferentes, quem marca e quem é o responsável? *Defeito:* a coordenação da primeira disciplina; confirmar.
- **Q18** (T7.6): um exame sem inscritos é retirado automaticamente? *Defeito:* só assinalado.
- **Q19** (T7.9): quem publica o calendário e quando deixa de ser rascunho. Bloqueia T7.9.
- **Q20** (T7.10): o que é «dia equivalente» ao copiar. *Defeito:* mesmo desvio desde o início da época, passado ao dia útil seguinte.
- ~~**Q24** (percursos, D75): o percurso é uma turma própria no 4.º ano, ou uma turma dividida em grupos por percurso?~~ Resolvida pelo utilizador: **são duas turmas, uma com cada percurso**; as disciplinas comuns podem juntar as duas turmas (D23). Fica por detalhar como se marca o que é comum e o que é de um percurso (T0.6). O plano real (`docs/Planos_EIC_TM.md`) mostra EIC com TIC e PSI e TM com as variantes Multimédia e Audiovisual; «percurso» e «variante» parecem o mesmo conceito.
- ~~**Q25** (matrícula prevista, D76)~~ Resolvida (D81): a estimada introduz-se **por turma e ano** e atualiza-se com a real; esta substitui aquela, e `size_change` dá o que T4.5 usará para assinalar as turmas cuja dimensão mudou. Falta o aviso ao coordenador (T4.5).
- **Q26** (plano real): os planos têm uma só coluna «P/L» (práticas/laboratoriais), mas o sistema tem os tipos P e L separados. Que tipo se regista nas disciplinas com P/L? *Defeito proposto:* o tipo P (pesam o mesmo na preparação, D61), ou criar um tipo combinado «P/L».
- **Q27** (plano real): a UCT do 8.º semestre (PFC, ETC, monografia) não tem horas semanais, só 45 ou 60 horas de contacto, e D60 exige carga semanal em toda a disciplina. Como se modela e como entra na carga? *Sem defeito.*
- **Q28** (plano real): a «Opção Condicionada» do 7.º semestre é uma vaga com cinco disciplinas alternativas (Robótica e Automação, Tecnologias Avançadas de Redes, Processamento de Imagem e Biométrica, Economia e Gestão, Inglês Técnico). Como se modela? *Sem defeito.*
- **Q29** (T6.5): que aspeto se espera da interface? Falta uma referência (exemplos de ecrãs de que gosta, cores e logótipo da Uni-CV, o ecrã que mais lhe interessa) e se o menu deve ser lateral ou superior. *Sem defeito:* não se desenha sem referência.

## Informação nova a incorporar (02/11/2026)
- **Matrícula (D81, D82):** os Serviços Académicos introduzem o número por turma, primeiro estimado e depois atualizado; no futuro a estimada poderá calcular-se com dados históricos do SII e a real obter-se por consulta à base do SII. Sem trabalho agora.
- **Percursos (D75):** alguns cursos têm vários percursos no 4.º ano (EIC: TIC e PSI), com disciplinas comuns e próprias. Toca T1.5, T2.3, T3.1 a T3.4, T4.5 e a vista por curso. ⚑ Q24
- **Matrícula prevista e real (D76):** o DSD faz-se com matrícula prevista e atualiza-se quando chega a real. Toca T1.2, T1.5, T3.2 e T4.5 (alerta de dimensão alterada); modelo e regra em T1.1 (D81).
- **Planos vindos do SII (D77):** futuro; sem trabalho agora, mas sem decisões que o impeçam.

## Critério de fim da fase 2
Com dados fictícios, o gestor cria o DSD e abre os semestres; cada coordenador junta e divide turmas, atribui docentes e regista a componente não letiva; o sistema calcula a carga e mostra o estado certo nos quatro níveis (**Porta 1**: coincide com o Excel em todos os docentes, ou as diferenças ficam explicadas); os exames das três épocas ficam marcados sem conflitos de turma, sala ou júri, com a concorrência garantida pela BD; cada perfil vê e altera só o seu âmbito; tudo na auditoria; testes a passar.
