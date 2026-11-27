import json, sys
d = json.load(open(sys.argv[1]))
c = d["categories"]; a = d["audits"]
print(sys.argv[2], {k: round(v["score"] * 100) for k, v in c.items()},
      "LCP", a["largest-contentful-paint"]["displayValue"],
      "CLS", a["cumulative-layout-shift"]["displayValue"],
      "TBT", a["total-blocking-time"]["displayValue"])
for k, v in a.items():
    if v.get("score") is not None and v["score"] < 0.9 and v.get("scoreDisplayMode") in ("binary", "numeric", "metricSavings"):
        print("   -", k, ":", v["title"], "|", v.get("displayValue", ""))
