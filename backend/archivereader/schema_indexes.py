"""Idempotent indexes for hot lookups, including already-created feature tables."""
INDEXES={
 'idx_records_page':('records','page'),
 'idx_annotations_page':('annotations','page'),
 'idx_person_members_person':('person_members','person'),
 'idx_book_tasks_job_state':('book_tasks','job,state'),
 'idx_line_history_page_line':('line_history','page,line'),
 'idx_book_items_page':('book_items','page'),
}

def ensure_indexes(db):
    existing={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    installed={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    changed=False
    for name,(table,columns) in INDEXES.items():
        if table in existing and name not in installed:
            db.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table}({columns})');changed=True
    if changed:db.commit()
