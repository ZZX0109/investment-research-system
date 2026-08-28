"""List akshare functions relevant to forecast / notice / announcement / guidance."""
import akshare as ak
names = [n for n in dir(ak) if not n.startswith("_")]
for kw in ["forecast", "notice", "disclos", "announce", "report_em", "yindao", "yjyg", "performance", "analyst", "rating", "research_report", "agency"]:
    hits = [n for n in names if kw in n.lower()]
    print("=== {} ===".format(kw))
    for h in hits:
        print("  ", h)
