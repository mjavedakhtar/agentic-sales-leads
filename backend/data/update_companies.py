import json

with open('backend/data/companies.json', 'r') as f:
    data = json.load(f)

hyps = {
    'assemblies-de': "An operating manufacturing site is CloudScale ICP. Current stack, named OT/IT owner, and in-market intent (jobs, RFP, or program) are not established.",
    'electronics-dach': "Electronics manufacturing is CloudScale ICP for automated QA. Incumbent stack, named buyer, and in-market intent remain unknown unless the source names them.",
    'molders-de': "High-volume manufacturing is DataStream ICP. MQTT/OPC UA/Kafka use, on-prem constraints, named OT owner, and intent signals are not in this capture.",
}

for scenario, default_hyp in hyps.items():
    for company in data.get(scenario, []):
        if company.get('hold') or company['id'] in ('liebherr', 'quantec'):
            continue
        company['hypothesis'] = default_hyp

for company in data.get('electronics-dach', []):
    if company['id'] == 'quantec':
        company['application'] = 'Insufficient source evidence'
        company['hypothesis'] = 'Do not treat the search result as qualified company evidence. Fetch a relevant source before making an application, stack, intent, or buyer claim.'

with open('backend/data/companies.json', 'w') as f:
    json.dump(data, f, indent=2)
