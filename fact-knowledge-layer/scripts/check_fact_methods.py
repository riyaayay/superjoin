"""Check stored fact extraction methods per document."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from fkl.persistence import database, repositories
from collections import Counter

db = database.get_session()

DOC_IDS = [
    'doc_b1278d3ccb0c419d',  # annual report
    'doc_4f0034e7245d44e0',  # investor deck
    'doc_d792b170cbb54935',  # meridian
    'doc_d6c660577ee44afd',  # prospectus
]

for doc_id in DOC_IDS:
    doc = repositories.get_document(db, doc_id)
    if not doc:
        print(f'{doc_id}: NOT FOUND')
        continue
    stats = repositories.get_document_stats(db, doc_id)
    print(f'\n--- {doc.original_filename} ---')
    print(f'  stored page_count      = {doc.page_count}')
    print(f'  facts_accepted         = {stats["facts_accepted"]}')
    print(f'  relationships          = {stats["relationships"]}')

    for r in doc.runs:
        ptotal = getattr(r, 'prose_blocks_total', None)
        pllm = getattr(r, 'prose_blocks_llm_called', None)
        rel_created = r.relationships_created
        print(f'  run {r.id[:14]}: prose_total={ptotal} prose_llm_called={pllm} facts_created={r.facts_created} rels={rel_created}')

    facts = repositories.get_facts_for_document(db, doc_id)
    methods = Counter(f.extraction_method for f in facts)
    print(f'  extraction methods: {dict(methods)}')

    if facts:
        print(f'  Sample accepted facts (first 3):')
        for f in facts[:3]:
            print(f'    [{f.extraction_method}] entity={f.entity_raw!r} metric={f.metric_raw!r} value={f.value_raw!r}')

db.close()
