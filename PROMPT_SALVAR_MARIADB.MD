# ESPECIFICAÇÃO TÉCNICA: Persistência de Session State (Streamlit + PHP/MariaDB)

## 1. VISÃO GERAL E OBJETIVO
Desenvolver um sistema robusto para persistir o estado da sessão (`st.session_state`) de um aplicativo Streamlit em um banco de dados remoto (MariaDB) via API PHP. O sistema deve identificar usuários recorrentes através de Cookies criptografados ou UUIDs persistentes.

### Stack Tecnológica
- **Frontend:** Streamlit (Python) + `extra-streamlit-components` (Cookie Manager).
- **Backend:** PHP 8.2+ (API REST com PDO e Tipagem forte).
- **Banco de Dados:** MariaDB 11.x (Uso de colunas nativas JSON).
- **Segurança:** Autenticação via Bearer Token.

---

## 2. ARQUITETURA DE DADOS

### 2.1 Estrutura do Objeto JSON (Payload)
O Python deve serializar o estado da sessão. Objetos complexos (DataFrames, Numpy Arrays) devem ser convertidos para formatos serializáveis (dict ou list).

```json
{
  "session_uuid": "550e8400-e29b-41d4-a716-446655440000",
  "session_name": "Análise de Risco - 2025",
  "app_version": "1.0.0",
  "is_incognito": false,
  "last_step": "upload_file",
  "data": {
    "user_inputs": { "age": 30, "salary": 5000 },
    "processed_data": [ ... ], 
    "flags": { "has_error": false }
  }
}
```

## 2.2 Schema do Banco de Dados (SQL)
Criar a tabela `app_sessions` no MariaDB.

```SQL
CREATE TABLE app_sessions (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    session_uuid CHAR(36) NOT NULL UNIQUE,
    session_name VARCHAR(255),
    json_data JSON NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_uuid (session_uuid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```


