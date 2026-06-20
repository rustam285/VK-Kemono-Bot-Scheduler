-- Миграция: добавление поддержки Telegram в таблицу scheduled_posts
-- Выполнить в Supabase SQL Editor

ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'vk';
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS tg_message_ids JSONB;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS tg_channel TEXT;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS tg_channel_title TEXT;
