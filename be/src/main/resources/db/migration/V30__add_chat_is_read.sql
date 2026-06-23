ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS is_read BOOLEAN NOT NULL DEFAULT true;

-- user 역할은 본인 메시지이므로 읽음, assistant/alert는 미읽음으로 초기화
UPDATE chat_messages SET is_read = false WHERE role IN ('assistant', 'alert');
