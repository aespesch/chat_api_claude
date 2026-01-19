# PROJETO: Persistência de Session State do Streamlit via MariaDB

## CONTEXTO
- Aplicativo Streamlit que perde dados quando fica inativo
- Servidor PHP/MariaDB disponível em: https://www.ita90.com.br/claude/json
- MariaDB: 11.8.3-MariaDB-log
- PHP Version: 7.4.33
- Objetivo: salvar e recuperar st.session_state de forma persistente

## ARQUITETURA
```
[Streamlit APP.PY] <--JSON via HTTP--> [PHP API] <--SQL--> [MariaDB]
```

## ETAPAS DE IMPLEMENTAÇÃO

### ETAPA 1: Estrutura do JSON
**Objetivo:** Definir formato do JSON que representará o session_state
**Entregável:** Exemplo de JSON com estrutura definida
**Considerações:**
- Incluir `session_id` (identificador único)
- Incluir `timestamp` (data/hora)
- Incluir `data` (objeto com todas as variáveis)
- Definir quais variáveis do session_state serão persistidas (todas ou filtradas?)

### ETAPA 2: Modelo de Dados MariaDB
**Objetivo:** Criar tabela(s) para armazenar o JSON
**Entregável:** Script SQL CREATE TABLE
**Considerações:**
- Campo `session_id` como chave primária (VARCHAR/UUID)
- Campo `json_data` (TEXT? JSON?)
- Campo `created_at` (DATETIME)
- Campo `updated_at` (DATETIME)
- Índices necessários

### ETAPA 3: PHP - Endpoint de Escrita (SAVE)
**Objetivo:** Receber JSON via POST e salvar no MariaDB
**Entregável:** Arquivo `save.php`
**URL:** https://www.ita90.com.br/claude/json/save.php
**Considerações:**
- Método: POST
- Receber JSON no body
- Validar token de autenticação (header ou parâmetro)
- INSERT ou UPDATE (UPSERT) baseado no session_id
- Retornar JSON com status (success/error)

### ETAPA 4: APP.PY - Função de Salvar
**Objetivo:** Serializar session_state e enviar para PHP
**Entregável:** Função `save_session_to_remote()`
**Considerações:**
- Converter session_state para JSON (tratar tipos não serializáveis)
- Enviar via requests.post()
- Tratar erros de conexão
- Definir quando salvar (botão manual? automático? ao sair?)

### ETAPA 5: PHP - Endpoint de Leitura (LOAD)
**Objetivo:** Ler MariaDB e retornar JSON
**Entregável:** Arquivo `load.php`
**URL:** https://www.ita90.com.br/claude/json/load.php
**Considerações:**
- Método: GET
- Parâmetro: session_id
- Validar token de autenticação
- Retornar JSON com dados ou erro se não encontrado

### ETAPA 6: APP.PY - Função de Carregar
**Objetivo:** Buscar JSON do PHP e popular session_state
**Entregável:** Função `load_session_from_remote()`
**Considerações:**
- Chamar via requests.get()
- Deserializar JSON
- Popular st.session_state com os dados
- Executar no início do app (se session_id existir)

## CONFIGURAÇÕES NECESSÁRIAS
- Token de autenticação compartilhado (APP.PY e PHP)
- Credenciais MariaDB (apenas no PHP)
- Session_id: gravar como cookie na máquina do usuário?

## ARQUIVOS FINAIS
1. `app.py` - Aplicativo Streamlit modificado
2. `save.php` - Endpoint de escrita
3. `load.php` - Endpoint de leitura
4. `config.php` - Configurações do banco (variáveis secretas ficam em .env)
5. `schema.sql` - Script de criação do banco

## Considerações finais
1. O session_id será definido automaticamente e guardado em cookie no browser do usuário.
2. Usuário pode identificar a sessão com um nome. Enquanto ele não fizer isso, definir um nome temporário baseado no prompt.
3. Salvar automaticamente, a não ser quando o usuário estiver em modo incógnito.
