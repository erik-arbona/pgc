# PGC – Requisitos não funcionais e arquitetura

> Parte da especificação da PGC (Plataforma de Gestão das Coordenações – Uni-CV). Fonte: documento do projeto, versão de 31/10/2026.

## Requisitos não funcionais

| Requisito | Meta |
| --- | --- |
| Segurança | Autenticação por conta institucional, perfis com mínimo de permissões, ligação cifrada (HTTPS) |
| Rastreabilidade | Cada alteração regista utilizador, data, valor anterior e motivo |
| Integridade | Chaves e restrições na base de dados; um docente é uma só pessoa em todos os cursos |
| Disponibilidade e cópias | Cópia de segurança diária e teste de restauro antes de cada período de distribuição e de cada época de exames |
| Usabilidade | Vistas organizadas por tarefa, mais legíveis do que o Excel (visão geral, ficha do docente, atribuição por disciplina, calendário de exames); avisos no momento; consulta também no telemóvel |
| Interoperabilidade | Integração com o SII (matrículas, inscritos, docentes e atribuição docente–disciplina); exportação para Excel, CSV, Word e PDF; API para ligar mais tarde a horários |
| Privacidade | Dados pessoais dos docentes e dos estudantes limitados ao necessário e visíveis conforme o perfil; as listas de estudantes de cada exame só são visíveis para a coordenação, o docente responsável e o júri desse exame, e nunca na vista pública |

## Arquitetura do sistema

O sistema é um monólito modular: uma única aplicação web, com uma base de dados relacional e processos de tarefas em segundo plano, instalada num servidor da Uni-CV. Para a PGC, usada por centenas de pessoas, é a solução mais simples de construir, manter e auditar. A mesma arquitetura serve os restantes módulos da PGC, incluindo os horários, com quatro acrescentos já previstos: um motor de geração de horários, uma fila de tarefas robusta, um editor de horários interativo e uma camada de publicação para milhares de leitores.

### Interface

A interface da PGC não reproduz as folhas de Excel: em vez de uma grelha com todas as colunas, organiza-se em vistas, cada uma a responder a uma pergunta.

- **Visão geral da coordenação:** o que precisa de atenção (aulas por atribuir, propostas a concurso, docentes fora do intervalo, prazos) e a carga letiva anual de cada docente numa barra, com o intervalo mínimo–máximo e o estado em cor e em texto.
- **Ficha do docente:** por semestre, as aulas por disciplina, tipo de aula e turma ou grupo, a preparação calculada e as outras atividades; é também a vista que o docente consulta, só em leitura.
- **Atribuição por disciplina:** cada disciplina com as suas aulas por tipo, turma ou grupo, docente e sala pedida; o que falta atribuir destaca-se, e as ações (atribuir, juntar ou dividir turmas, propor a concurso, copiar do ano anterior) ficam junto da disciplina.
- **Calendário de exames:** por época, os dias ocupados de cada turma e as salas livres, com as junções, os grupos, a faixa horária, a sala, o docente responsável e o júri de cada exame.
- **Vista por curso:** o DSD e o calendário de exames de um curso, reunindo todas as coordenações que lhe dão aulas, com filtros combináveis (ano, semestre, turma, tipo de aula, docente); as disciplinas transversais aparecem em cada curso, marcadas como partilhadas, e as suas horas contam uma só vez nos totais gerais; o que falta no plano (disciplina sem turma, sem docente ou sem exame) destaca-se. Está disponível para os coordenadores, que são também os diretores de curso, e para o Conselho Executivo; o que pertence a outras coordenações aparece só em leitura.
- **Área do gestor da PGC:** docentes e cargos, planos e disciplinas (incluindo as disciplinas transversais), intervalos de horas, faixas horárias dos exames e contas.

A exportação para Excel, Word e PDF mantém-se para quem precisar dos documentos no formato atual. Uma proposta visual destas vistas acompanha este documento.

### Componentes

| Componente | Tecnologia proposta | Função | Quando |
| --- | --- | --- | --- |
| Proxy | Nginx com certificado HTTPS | Recebe os pedidos, cifra a ligação e serve a cache das páginas publicadas | Desde o início |
| Aplicação web | Python 3 com Django | Regras de negócio, perfis e permissões, ecrãs, relatórios e exportações | Desde o início |
| Interface | Páginas geradas no servidor com HTMX, organizadas por vistas (visão geral, ficha do docente, atribuição por disciplina, calendário de exames), sem grelha tipo Excel | Ecrãs do DSD e do calendário de exames, organizados por tarefa | Desde o início |
| Editor de horários | Componente interativo dentro da mesma aplicação (por exemplo, FullCalendar ou uma pequena parte em React) | Grelha semanal com arrastar e largar e avisos de conflito imediatos | Horários |
| Base de dados | PostgreSQL | Dados, versões do DSD e dos calendários de exames (e, mais tarde, dos horários), registo de auditoria | Desde o início |
| Fila de tarefas | Celery com Redis | Correio eletrónico, sincronização com o SII, relatórios pesados e, mais tarde, a geração de horários, com progresso visível e possibilidade de cancelar | Desde o início |
| Motor de horários | Ferramenta existente (FET ou UniTime) ligada por exportação e importação, ou motor próprio com Google OR-Tools (CP-SAT) | Gera horários sem conflitos a partir do DSD fechado, das salas e das disponibilidades | Horários |
| Publicação | Páginas só de leitura em cache e exportação iCal | Calendário de exames publicado (já na fase 2) e, mais tarde, horários, para milhares de estudantes e docentes, inclusive no telemóvel, sem carregar a aplicação | Calendário de exames (fase 2) |
| Autenticação | Conta institucional (LDAP/Active Directory ou SSO, a confirmar com os serviços informáticos) | Entrada sem nova palavra-passe | Desde o início |
| Cópias de segurança | Cópia diária da base de dados para outro servidor | Restauro testado antes de cada período de distribuição e de cada época de exames | Desde o início |

### Módulos da aplicação

Cada um dos dez blocos funcionais é uma componente própria dentro da aplicação (uma *app* Django), com os seus dados, ecrãs e testes. Um núcleo comum trata dos utilizadores, perfis, permissões e auditoria. As regras de cálculo da carga ficam num módulo isolado, sem dependência dos ecrãs, para poderem ser testadas exaustivamente.

A aplicação é desenhada como plataforma: o núcleo partilhado (estrutura académica, docentes, turmas, salas, utilizadores e calendário) fica em componentes próprios, independentes do DSD. O núcleo inclui o tempo desde o início: calendário letivo, grelha de franjas horárias de cada Faculdade, disponibilidade dos docentes e indicação das salas partilhadas entre Faculdades. O módulo de horários entrará mais tarde como mais um conjunto de componentes sobre a mesma base de dados, sem mudar a arquitetura.

Como várias pessoas editam ao mesmo tempo, a aplicação usa bloqueio otimista: se duas pessoas alteram a mesma turma, grupo ou sala, a segunda é avisada e vê a alteração da primeira antes de gravar.

### Permissões

Cada utilizador tem um perfil e um âmbito. O âmbito diz sobre que dados pode agir: o coordenador, só sobre a sua coordenação; o utilizador do Conselho Executivo, só sobre a sua Faculdade; o gestor da PGC, sobre a Faculdade ou as Faculdades que lhe forem atribuídas; a consulta, só leitura; o docente, só leitura da sua própria distribuição; na vista por curso, o coordenador vê em leitura o DSD e os exames das outras coordenações, sem as listas de estudantes desses exames; nos exames, o coordenador marca só os das disciplinas da sua coordenação e vê os das outras nas mesmas turmas. As permissões verificam-se sempre no servidor, nunca apenas no ecrã.

### Versões e auditoria

- Cada alteração fica num registo de auditoria: quem, quando, valor anterior, valor novo e motivo.
- O fecho de um DSD cria uma versão imutável; as alterações posteriores criam versões novas e nunca reescrevem as anteriores.
- Os intervalos de horas guardam-se com data de vigência, para que um DSD fechado se possa sempre recalcular com os valores do seu tempo.

### Integrações

| Sistema | Sentido | O que passa | Meio |
| --- | --- | --- | --- |
| SII | Entrada | Matrículas e dados dos docentes | API, ligação à base de dados ou ficheiros CSV, a confirmar |
| SII | Saída | Atribuição docente–disciplina depois do fecho | Idem |
| Correio eletrónico | Saída | Prazos, recusas, fecho e alterações de exames em turmas comuns | Servidor de correio institucional (SMTP) |
| Horários | Saída | Disciplinas, turmas, grupos, docentes e tipo de sala | Interno: o módulo de horários lê o DSD fechado na base de dados partilhada; exportação e API de leitura para outras ferramentas |
| SII | Entrada | Lista de estudantes inscritos em cada exame (por disciplina e época), em cada semestre; substitui o Excel enviado hoje às coordenações | Idem |
| Calendário de exames | Saída | Calendário por época, curso e ano, com disciplina, inscritos, data, hora, sala e júri | Word e PDF no formato atual; vista pública só de leitura |

### Ambientes e desenvolvimento

- Três ambientes, todos em contentores: desenvolvimento, teste e produção.
- Código num repositório Git institucional, com integração contínua que corre os testes antes de cada entrega.
- Desenvolvimento assistido por IA (*vibe coding*), módulo a módulo: especificação escrita, geração do código, testes automáticos e revisão humana antes de entrar em produção.
- Nenhuma alteração em produção durante a janela de distribuição do DSD nem durante a marcação dos exames.

### Decisões de arquitetura

| Decisão | Escolha | Alternativa posta de parte | Porquê |
| --- | --- | --- | --- |
| Estilo | Monólito modular | Microsserviços | Equipa pequena; menos peças para manter; aguenta também os restantes módulos da PGC |
| Linguagem e framework | Python com Django | Node.js, Java | Autenticação, permissões e administração de origem; a equipa técnica domina Python; as melhores bibliotecas de otimização para horários estão em Python; bom suporte na geração de código por IA |
| Interface | HTMX em geral e um componente interativo só no editor de horários | Aplicação separada (React) para tudo | Menos código e menos pontos de falha; a riqueza só onde é precisa |
| Base de dados | PostgreSQL | MySQL | Restrições e integridade fortes, adequadas a um problema feito de relações |
| Tarefas | Celery com Redis | Django-Q | A geração de horários é longa e precisa de progresso, cancelamento e um contentor próprio |
| Motor de horários | Integrar primeiro uma ferramenta existente (FET ou UniTime) | Construir de raiz | O motor é a parte mais difícil de gerar e verificar; um motor próprio com OR-Tools fica como segunda opção, se as regras da Uni-CV o exigirem |
| Publicação | Cache só de leitura e iCal | Servir cada consulta pela aplicação | Milhares de estudantes a consultar ao mesmo tempo sem afetar quem trabalha na PGC |
| Plataforma | Aplicação própria | Módulo do Moodle | Os modelos do DSD e do calendário de exames ficam desajustados no modelo de dados do Moodle |

