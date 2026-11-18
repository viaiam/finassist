-- 仅初始化融知客服自己的会话库，不修改已有业务库。
CREATE DATABASE IF NOT EXISTS finassist CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE finassist;
CREATE TABLE IF NOT EXISTS dialogue_states (
    sender_id VARCHAR(255) PRIMARY KEY,
    state_json TEXT NOT NULL
) CHARACTER SET utf8mb4;
