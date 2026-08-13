ALTER TABLE artifacts DROP CONSTRAINT IF EXISTS artifacts_type_check;
ALTER TABLE artifacts ADD CONSTRAINT artifacts_type_check
    CHECK (type IN ('chart','report','documentation','summary','presentation','project_files'));
