-- Phase 7: FTS5 full-text search for memories (no new Python deps)

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    key,
    category,
    content='memories',
    content_rowid='id'
);

INSERT INTO memories_fts(memories_fts) VALUES('rebuild');

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, key, category)
    VALUES (new.id, new.content, IFNULL(new.key, ''), IFNULL(new.category, ''));
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, key, category)
    VALUES ('delete', old.id, old.content, IFNULL(old.key, ''), IFNULL(old.category, ''));
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, key, category)
    VALUES ('delete', old.id, old.content, IFNULL(old.key, ''), IFNULL(old.category, ''));
    INSERT INTO memories_fts(rowid, content, key, category)
    VALUES (new.id, new.content, IFNULL(new.key, ''), IFNULL(new.category, ''));
END;
