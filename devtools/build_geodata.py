"""Rebuild dashboard/geodata from GeoNames (only needed to refresh the bundled lists).

    pip install geonamescache
    python devtools/build_geodata.py

Writes dashboard/geodata/places.tsv.gz (every town with 1,000 people or more:
geonameid, name, lat, lon, country, population) and countries.tsv (code, name).
Data: GeoNames (https://www.geonames.org), CC BY 4.0, via the geonamescache package (MIT).
"""
import gzip
import json
import os

import geonamescache

OUT = os.path.join(os.path.dirname(__file__), "..", "dashboard", "geodata")


def main():
    data = os.path.join(os.path.dirname(geonamescache.__file__), "data")
    with open(os.path.join(data, "cities1000.json"), encoding="utf-8") as f:
        cities = json.load(f).values()
    with open(os.path.join(data, "countries.json"), encoding="utf-8") as f:
        countries = json.load(f).values()
    os.makedirs(OUT, exist_ok=True)
    rows = sorted(cities, key=lambda c: (c["countrycode"], -int(c["population"] or 0), c["name"]))
    with gzip.open(os.path.join(OUT, "places.tsv.gz"), "wt", encoding="utf-8", compresslevel=9) as f:
        f.write("# GeoNames cities1000 (https://www.geonames.org), CC BY 4.0. geonameid, name, lat, lon, country, population\n")
        for c in rows:
            name = c["name"].replace("\t", " ").strip()
            f.write(f"{c['geonameid']}\t{name}\t{round(c['latitude'], 4)}\t{round(c['longitude'], 4)}\t{c['countrycode']}\t{int(c['population'] or 0)}\n")
    with open(os.path.join(OUT, "countries.tsv"), "w", encoding="utf-8") as f:
        f.write("# GeoNames countryInfo (https://www.geonames.org), CC BY 4.0. code, name\n")
        for c in sorted(countries, key=lambda c: c["iso"]):
            f.write(f"{c['iso']}\t{c['name']}\n")
    print(f"{len(rows)} places, {len(countries)} countries written to {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
