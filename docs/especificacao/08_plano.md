# PGC – Dados de partida, plano e recursos

> Parte da especificação da PGC (Plataforma de Gestão das Coordenações – Uni-CV). Fonte: documento do projeto, versão de 31/10/2026.

## Dados de partida

Não se importam os DSD nem os calendários de exames atuais. O gestor da PGC introduz disciplinas e docentes a partir dos planos de estudos e dos dados dos docentes; os Serviços Académicos introduzem as matrículas, de preferência a partir do SII; e o Património introduz as salas. Assim o sistema começa com dados limpos, sem herdar cópias, grafias diferentes nem totais que não conferem.

Os ficheiros Excel atuais servem apenas de comparação durante o piloto: para cada coordenação, compara-se a carga calculada pelo sistema com a do DSD em Excel, docente a docente, e as diferenças explicam-se antes do fecho. Do mesmo modo, os calendários de exames em Word servem para conferir o primeiro calendário feito na PGC.

## Plano de implementação

**Fases** (diagrama do documento, em texto):

| Fase | Conteúdo | Duração estimada |
| --- | --- | --- |
| Fase 0 · Descoberta e regras | Fechar fórmulas de carga, perfis e circuito de aprovação | ≈ 4 semanas |
| Fase 1 · Base e importação | Cadastros, salas, contas e ligação ao SII | ≈ 6 semanas |
| Fase 2 · Núcleo do DSD | Turmas, grupos, carga, alertas e calendário de exames | ≈ 8 semanas |
| Porta 1 | A carga calculada coincide com a do Excel em todos os docentes | — |
| Fase 3 · Pedidos e relatórios | Concursos, calendário do DSD e relatórios | ≈ 8 semanas |
| Piloto em paralelo | Grupo de Faculdades, em paralelo com o Excel | 1 semestre |
| Porta 2 | O Conselho Executivo fecha no sistema o DSD de cada coordenação, sem Excel | — |
| Depois | Toda a Universidade; módulo de horários | contínua |


As durações são uma estimativa inicial, já a contar com o desenvolvimento assistido por IA, e têm de ser confirmadas na Fase 0. As fases não estão desenhadas à escala.

Somando as quatro fases de desenvolvimento, o sistema fica pronto para piloto cerca de seis meses após o arranque. Como os DSD costumam ser preparados no fim do ano letivo anterior, a distribuição de 2027/28 é o alvo natural do piloto: as coordenações de um grupo de Faculdades elaboram o DSD e o calendário de exames na PGC e, ao mesmo tempo, nos ficheiros atuais. Só se a Porta 2 for passada os ficheiros atuais deixam de ser usados e o sistema estende-se às restantes Faculdades.

## Equipa, recursos e riscos

**Equipa mínima:**

- Promotor do projeto: ICUB, que define regras e valida resultados.
- Responsável técnico e um a dois programadores, com desenvolvimento assistido por IA (*vibe coding*); pode contar com docentes e projetos finais de estudantes de Engenharia Informática, sob supervisão.
- Serviços informáticos da Uni-CV, para servidor, contas institucionais, cópias de segurança e acesso ao SII.
- Os gestores da PGC, um utilizador do Conselho Executivo de cada Faculdade do piloto, um representante de cada coordenação e interlocutores dos Serviços Académicos e do Património.

**Recursos:** um servidor Linux (ou máquina virtual) com espaço para a base de dados e cópias, um domínio interno da Uni-CV e certificado HTTPS.

**Orçamento de desenvolvimento (primeiro ano):** opção de custo mínimo, com desenvolvimento assistido por IA através do Claude Code.

| Conceito | Custo estimado | Observações |
| --- | --- | --- |
| Subscrição Claude Pro (Claude Code incluído) | 200 USD/ano | Pagamento anual (17 USD/mês); 20 USD/mês com pagamento mensal |
| Computador de desenvolvimento | ≈700–1.000 USD | Compra de um portátil ou computador de secretária: 16 GB de RAM, processador moderno de 6–8 núcleos, SSD de 512 GB, Linux (Ubuntu); preço a confirmar com fornecedores locais |
| **Total** | **≈900–1.200 USD** | Subscrição a preços oficiais de outubro de 2026, sem impostos; computador como estimativa; valores podem mudar |

O plano Pro tem limites de utilização (por janelas de 5 horas e por semana). Para os aproveitar ao máximo: especificações escritas antes de cada tarefa, tarefas pequenas e fechadas, um ficheiro de regras do projeto (CLAUDE.md), uso preferencial do modelo Sonnet e revisão do código gerado enquanto a quota não renova. Recomenda-se pagar mensalmente nos primeiros um ou dois meses e passar ao pagamento anual depois de confirmar que o plano chega. Se as esperas atrasarem o piloto, pode subir-se ao plano Max (a partir de 100 USD/mês) apenas num mês concreto. Durante o desenvolvimento usam-se dados fictícios ou anonimizados, nunca dados reais de docentes.

| Risco | Impacto | Mitigação |
| --- | --- | --- |
| Regras de cálculo diferentes entre cursos ou Faculdades | O sistema calcula «mal» para alguns | Regras como parâmetros por curso; validar com cada coordenador antes do piloto |
| Dados de base desatualizados (salas, inscritos, intervalos de horas) | Avisos e cálculos errados | Um responsável por cada fonte e data da última atualização visível no sistema |
| Resistência a abandonar o Excel | Dois processos em paralelo | Piloto em paralelo, exportação para Excel mantida e vistas mais claras do que o Excel, testadas com os coordenadores |
| Código gerado com IA | Erros difíceis de detetar nos cálculos | Testes automáticos das regras de cálculo, revisão humana e comparação com o Excel no piloto |
| Dependência de uma só pessoa | Sistema sem manutenção | Documentação, código em repositório institucional e pelo menos dois mantenedores |
| Prazos do DSD coincidem com o desenvolvimento | Sem tempo para testar | Entregar por fases e não alterar o sistema em produção durante a janela de distribuição |
| Acesso indevido a dados de docentes | Quebra de privacidade | Perfis, auditoria, HTTPS e revisão de permissões em cada semestre |
| Muitos acessos ao publicar o calendário de exames e, mais tarde, os horários | Sistema lento para quem trabalha na PGC | Publicação em cache só de leitura e exportação iCal |
| Motor de horários mais difícil do que o previsto | Atraso no módulo de horários | Começar por integrar FET ou UniTime e testar com dados reais antes de decidir |
| Limites de utilização do plano Pro | Desenvolvimento mais lento do que o previsto | Tarefas pequenas e bem especificadas; subir ao plano Max só no mês em que for necessário |

