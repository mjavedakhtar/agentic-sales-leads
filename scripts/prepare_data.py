"""One-time local capture curation. No network requests, credentials, or model calls.

Records are authored research interpretations over existing source captures.
Only source excerpts are observed; product suitability is always a hypothesis.
"""
from pathlib import Path
from html import unescape
import json
import hashlib
import shutil
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT.parent / "TechNova-gpt" / "seeds"
OUT = ROOT / "backend" / "data"
OUT.mkdir(parents=True, exist_ok=True)

def clean(s):
    return unescape(s).replace("\u2014", "-").strip()

# These labels are reviewable interpretations, never imported model extraction flags.
rows = {
 "batteries-de": ("CloudScale_ev_de.json", [
  dict(id="draexlmaier",name="DRÄXLMAIER Group",url="https://www.draexlmaier.com",country="Germany (research scope)",sector="Automotive / e-mobility",position="Tier-1 supplier to vehicle OEMs",application="Predictive maintenance",quote="Wir beliefern weltweit Premium-Fahrzeughersteller mit komplexen Bordnetz-Systemen, zentralen Elektrik- und Elektronik-Komponenten, exklusivem Interieur sowie Batteriesystemen für die Elektromobilität",claim="The captured company description names battery systems and supply to vehicle manufacturers.",hypothesis="OEM supply creates a plausible CloudScale ICP. Current stack, named OT/IT owner, and in-market intent are not established.",application_level="adjacent",sector_level="observed",position_level="observed"),
  dict(id="accumotive",name="Accumotive",url="https://www.accumotive.de",country="Germany",sector="Automotive / e-mobility",position="Plant operator (buyer unconfirmed)",application="Predictive maintenance",quote="In Kamenz bei Dresden entstehen die Batterien für die Elektrofahrzeuge von Mercedes-Benz.",claim="The captured company description says EV batteries are produced in Kamenz near Dresden.",hypothesis="An operating EV plant is CloudScale ICP. Deployment topology, incumbent stack, and who licenses inference software remain unknown.",application_level="adjacent",sector_level="observed",position_level="inferred"),
  dict(id="bmz",name="BMZ Group",url="https://bmz-group.com",country="Germany (research scope)",sector="Battery systems",position="Plant operator / system manufacturer",application="Predictive maintenance",quote="Als Batteriehersteller, entwickelt und produziert High-Tech-Batteriesysteme, die weltweit in den unterschiedlichsten Produkten namhafter Marken verbaut werden.",claim="The captured company description says it develops and manufactures battery systems.",hypothesis="Battery-system manufacture is adjacent ICP. Predictive-maintenance workload, stack, and buying committee are not evidenced here.",application_level="adjacent",sector_level="inferred",position_level="observed"),
  dict(id="liebherr",name="Liebherr",url="https://www.liebherr.com",country="Germany (research scope)",sector="Industrial equipment",position="Equipment supplier (research hypothesis)",application="Predictive maintenance",quote="Die Firmengruppe Liebherr ist einer der größten Baumaschinenhersteller der Welt",claim="The captured description identifies a construction machinery manufacturer; it does not establish battery-pack assembly.",hypothesis="Equipment supply alone does not establish that this company deploys or licenses CloudScale. Fetch an application-specific source before treating this as a software lead.",application_level="weak",sector_level="unknown",position_level="inferred",hold=True),
 ]),
 "electronics-dach": ("CloudScale_power_electronics_dach.json", [
  dict(id="phoenix",name="Phoenix PHD",url="https://www.phoenix-phd-gmbh.de",country="Germany (research scope)",sector="Electronics manufacturing",position="EMS provider (software buyer unconfirmed)",application="Automated quality assurance",quote="Als EMS-Dienstleister bietet Ihnen die Phoenix PHD GmbH ein breites Leistungsspektrum. Dazu gehören die Materialbeschaffung, die Leiterplattenbestückung, ein kompetenter Reparaturservice, das Prüfen und Testen der Baugruppen und die Gerätemontage.",extra_quote="Beschichtung und Verguss",claim="The captured description names EMS, component procurement and device assembly. It also lists coating and potting.",hypothesis="EMS assembly and QA testing are CloudScale ICP. The source names component procurement, not software licensing, stack, or a dated buying signal.",application_level="direct",sector_level="observed",position_level="observed"),
  dict(id="tps",name="TPS Elektronik",url="https://tps-elektronik.com",country="Germany (research scope)",sector="Power electronics",position="EMS provider",application="Automated quality assurance",quote="TPS Elektronik – Ihr EMS-Partner für Leistungselektronik und kundenspezifische Lösungen.",extra_quote="Leistungsstarker EMS Dienstleister mit Produkten von Kühlung, Stromversorgung, Busbars",claim="The captured metadata identifies EMS for power electronics and names cooling and busbar products.",hypothesis="Power-electronics EMS is adjacent ICP for visual QA. Incumbent stack, named buyer, and in-market intent remain unknown.",application_level="adjacent",sector_level="observed",position_level="observed"),
  dict(id="miba",name="Miba Cooling",url="https://www.dau-heatsinks.com",country="Austria",sector="Power electronics cooling",position="Component manufacturer",application="Automated quality assurance",quote="Das Unternehmen entwickelt und fertigt Hochleistungskühlkörper für Leistungshalbleiter, die Motore und elektrische Antriebe steuern.",extra_quote="Standorten in Ligist (Steiermark, Österreich) und Macedon (NY, USA)",claim="The captured description states high-performance heat-sink manufacture and an Austrian location.",hypothesis="Heat-sink manufacture is adjacent to automated QA. The assembly customer may own the software purchase.",application_level="adjacent",sector_level="observed",position_level="inferred"),
  dict(id="quantec",name="Quantec Services",url="https://quantec-services.de",country="Germany (research scope)",sector="Unverified",position="Unverified",application="Insufficient source evidence",quote="Quisque blandit dolor risus, sed dapibus dui facilisis sed.",claim="The captured page contains placeholder copy. This capture cannot substantiate the discovery result.",hypothesis="Do not treat the search result as qualified company evidence. Fetch a relevant source before making an application, stack, intent, or buyer claim.",application_level="none",sector_level="unknown",position_level="unknown",hold=True),
 ]),
 "molders-de": ("DataStream_molders_de.json", [
  dict(id="buk",name="BUK Group",url="https://www.buk-group.de",country="Germany (research scope)",sector="Automotive (research hypothesis)",position="Plant operator (injection manufacturing)",application="Edge telemetry",quote="Wir stehen für leistungsstarken Kunststoffspritzguss: ✓ Großserien ✓ Metallsubstitution ✓ Medienführende Systeme ✓ Hochpräziser Werkzeugbau.",claim="The captured metadata names injection molding, large series, metal substitution and fluid-carrying systems.",hypothesis="High-volume manufacturing is DataStream ICP. MQTT/OPC UA/Kafka use, on-prem constraints, named OT owner, and intent signals are not in this capture.",application_level="adjacent",sector_level="inferred",position_level="observed"),
  dict(id="schroeder",name="Schröder + Heidler",url="https://www.schroeder-heidler.de",country="Germany",sector="Automotive (research hypothesis)",position="Plant operator / toolmaker",application="Edge telemetry",quote="Ihr Spezialist für Spritzguss, Werkzeugbau, 2K-Technik und Baugruppenmontage im Erzgebirge.",extra_quote="IATF 16949 zertifiziert",claim="The captured description names injection molding, tooling and assembly in the Erzgebirge, plus automotive quality certification.",hypothesis="The manufacturing process is relevant. Automotive certification does not establish telemetry stack, license owner, or in-market intent.",application_level="process",sector_level="inferred",position_level="observed"),
  dict(id="hehnke",name="Hehnke",url="https://hehnke.de",country="Germany (research scope)",sector="Automotive (research hypothesis)",position="Plant operator (injection manufacturing)",application="Edge telemetry",quote="Unsere Kernkompetenz liegt in Herstellung komplexer und individueller Bauteile und Baugruppen aus Kunststoff mittels Spritzgießen.",claim="The captured description names manufacture of complex plastic parts and assemblies by injection molding.",hypothesis="Injection manufacturing matches the process. Telemetry protocols, deployment topology, and software purchasing remain unknown.",application_level="process",sector_level="unknown",position_level="observed"),
 ])
}
# A self-reported organization-size signal, kept distinct from software demand.
for row in rows["molders-de"][1]:
    if row["id"] == "schroeder":
        row["employees_min"] = 115
        row["size_quote"] = '"numberOfEmployees":{"@type":"QuantitativeValue","minValue":115}'
result={}
for scenario,(file,items) in rows.items():
    seed=json.loads((INPUT/file).read_text())
    for row in items:
        raw=seed['pages'][row['url']]['text']
        page=clean(raw)
        assert clean(row['quote']) in page,(row['id'],'missing excerpt')
        if row.get('extra_quote'): assert clean(row['extra_quote']) in page,row['id']
        if row.get('size_quote'): assert row['size_quote'] in page,row['id']
        row['quote']=clean(row['quote'])
        row['captured_at']=seed['provenance']['frozen_at']
        row['source_capture']={"seed":file,"sha256":hashlib.sha256(raw.encode()).hexdigest(),"page_text":page,"normalization":"HTML entities decoded; em dash replaced with standard hyphen; outer whitespace trimmed"}
    result[scenario]=items
(OUT/'companies.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
products=[]
for product_id,filename,name,family,description,applications,specs in [
 ("CS-AI","case-study-fde-01-specsheet-CloudScale-ht.pdf","CloudScale AI","Enterprise AI Inference","High-throughput ML inference platform optimized for predictive maintenance and quality assurance in manufacturing.",["Predictive maintenance for EV assembly lines","Visual defect detection on factory lines","Supply chain anomaly detection"],[('Deployment','Cloud / Hybrid',1),('Max API Requests','50,000 RPM',1),('Data Residency','Global Regions (US, EU, APAC)',2)]),
 ("DS-PRO","case-study-fde-01-specsheet-DataStream-pa66-gf30.pdf","DataStream Pro","Edge Telemetry","Ultra-low latency edge data streaming and ingestion engine for factory floor telemetry.",["High-frequency sensor ingestion for automotive manufacturing","Industrial IoT edge preprocessing","Robotics telemetry aggregation"],[('Max Throughput','1M events/sec',1),('Supported Protocols','MQTT, OPC UA, Kafka',1),('Deployment','On-Premises Edge Only',2)])
]:
    source=ROOT.parent/'common'/'specsheets'/filename
    target=OUT/'documents'/filename
    target.parent.mkdir(exist_ok=True)
    shutil.copyfile(source,target)
    chunks=[]
    for page_number,page in enumerate(PdfReader(source).pages,1):
        txt=clean(page.extract_text())
        # Page-addressable 900-character windows with 120-character overlap.
        for index,start in enumerate(range(0,len(txt),780)):
            chunk=txt[start:start+900]
            if not chunk.strip():continue
            chunks.append(dict(id=f'{product_id}-p{page_number}-c{index+1}',product_id=product_id,title=f'{name} / page {page_number}',text=chunk,page=page_number,source=filename))
    products.append(dict(id=product_id,name=name,family=family,description=description,applications=applications,specs=[dict(label=k,value=v,page=p) for k,v,p in specs],chunks=chunks,document_url='/api/documents/'+filename,fictional=True))
(OUT/'products.json').write_text(json.dumps(products,ensure_ascii=False,indent=2))
print(f'Curated {sum(map(len,result.values()))} captured company records and {sum(len(x["chunks"]) for x in products)} PDF chunks.')
