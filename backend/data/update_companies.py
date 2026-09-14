import json

with open('backend/data/companies.json', 'r') as f:
    data = json.load(f)

# Update batteries-de
for company in data.get('batteries-de', []):
    company['application'] = "Predictive maintenance"
    company['hypothesis'] = "assembly systems create a plausible use case for predictive maintenance AI. Deployment constraints and API limits need confirmation."

# Update electronics-dach
for company in data.get('electronics-dach', []):
    company['application'] = "Automated quality assurance"
    company['hypothesis'] = "An explicitly listed manufacturing process creates a relevant opening for quality assurance AI. API limits and latency requirements remain unknown."

# Update molders-de
for company in data.get('molders-de', []):
    company['application'] = "Edge telemetry"
    company['hypothesis'] = "Automotive manufacturing is a plausible use case for edge telemetry and high-frequency sensor ingestion. Required protocols and deployment constraints remain unknown."
    
with open('backend/data/companies.json', 'w') as f:
    json.dump(data, f, indent=2)
