import re

SOURCES = [
    ('building_practitioners', 'Building Practitioners Board decisions + LBP register', 'professional-register'),
    ('candidate_returns', 'Electoral Commission candidate returns (general elections)', 'election-finance'),
    ('charities', 'Charities Register (entities, officers, returns)', 'charity-register'),
    ('commerce_commission', 'Commerce Commission case register', 'regulator-enforcement'),
    ('council_minutes', 'Council meeting minutes (InfoCouncil)', 'council-governance'),
    ('council_procurement', 'Council procurement terms pages', 'procurement-notice'),
    ('councillor_interests', "Councillors' registers of interests", 'council-governance'),
    ('courts', 'courtsofnz.govt.nz case pages + judgment PDFs (estate copy)', 'judicial-decision'),
    ('courts-era', 'Employment Relations Authority determinations (estate copy)', 'judicial-decision'),
    ('courts-finder', 'Ministry decisions finder decisions (estate copy)', 'judicial-decision'),
    ('courts-jdo', 'Judicial Decisions Online decision PDFs (estate copy)', 'judicial-decision'),
    ('courts-survey', 'Court and tribunal site survey (reference pages)', 'judicial-decision'),
    ('disclosures', 'Electoral Commission donation disclosures', 'election-finance'),
    ('fma', 'FMA warnings and enforcement actions', 'regulator-enforcement'),
    ('grants', 'Class 4 gaming and Lottery grants', 'funding-grant'),
    ('iwi_directory', 'Te Kahui Mangai (iwi and hapu directory)', 'indigenous-directory'),
    ('local_elections', 'Local election candidate returns (council sites)', 'election-finance'),
    ('real_estate_authority', 'Real Estate Authority decisions', 'professional-disciplinary'),
    ('settlement_commitments', 'Te Haeata settlement commitments (watched pages)', 'treaty-settlement'),
    ('tenancy_tribunal', 'Tenancy Tribunal orders', 'judicial-decision'),
    ('worksafe', 'WorkSafe prosecutions and undertakings', 'regulator-enforcement'),
]

TPL = '''  estate-{name}:
    label: "{label} (estate capture, handed over 2026-11-05)"
    source_category: {cat}
    kind: records
    id_field: sha256
    date_field: [fetched_at, landed_at]
    title_field:
      - "names[0]"
      - "urls[0].url"
    text_fields: [names, urls]
    file_fields: [file]
    doc_type_field: kind
    record_file: /opt/data/querynz-estate/sources/{name}/manifest.jsonl
    path_root: /opt/data/querynz-estate/sources/{name}
    freshness_sla_hours: 720
'''

entries = '\n' + ''.join(TPL.format(name=n, label=l.replace('"', "'"), cat=c)
                         for n, l, c in SOURCES)

path = '/opt/data/qnz-mcp/corpora.yaml'
text = open(path).read()
marker = '\n# The `gaps` tool:'
assert marker in text, 'gaps marker not found'
assert 'estate-charities' not in text, 'already inserted'
text = text.replace(marker, '\n' + entries + marker.lstrip('\n'), 1)
open(path, 'w').write(text)
print('inserted', len(SOURCES), 'corpus entries')
