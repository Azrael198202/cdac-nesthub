import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_core.web_evidence_optimizer.optimizer import WebEvidenceOptimizer

html = '''
<html><body>
<header>brand header menu login</header>
<nav>home docs pricing menu</nav>
<aside class="sidebar">related ads promo</aside>
<div id="cookie-banner">cookie accept</div>
<main>
  <article>
    <p>Runtime components can prepare structured implementation evidence from official reference text.</p>
    <p>Connection configuration should be represented as typed schema values and validated before execution.</p>
    <pre>def run(config): return {"status": "ok"}</pre>
  </article>
</main>
<footer>copyright footer links</footer>
<script>bad()</script>
</body></html>
'''
opt = WebEvidenceOptimizer()
result = opt.optimize(
    user_input="prepare implementation evidence schema validation",
    documents=[{"url":"https://docs.example.org/reference", "title":"Reference", "text_excerpt":html}],
    max_items=3,
    batch_size=2,
    batch_top_k=1,
    token_budget=300,
)
assert result["status"] == "verified", result
joined = " ".join(item.get("evidence_excerpt", "") for item in result["evidence_pack"])
for forbidden in ["brand header", "home docs pricing", "cookie accept", "copyright footer", "related ads"]:
    assert forbidden not in joined, joined
assert "structured implementation evidence" in joined or "typed schema" in joined, joined
report = result["optimizer_report"]
assert report["batch_size"] == 2, report
assert report["batch_top_k"] == 1, report
assert report["selected_evidence_count"] <= 3, report
print("verify_web_cleaning_batch_optimizer: OK")
