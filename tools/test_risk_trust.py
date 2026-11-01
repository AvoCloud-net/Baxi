"""Tests für die Vertrauensregeln (assets/moderation/risk.py) und die Stufenwahl (safetext/pipeline._level).

    python tools/test_risk_trust.py

Läuft ohne Discord und ohne Datenbank (Abhängigkeiten werden durch Stubs ersetzt).
Regeln: Vertrauen nur bei >= 30 Tagen im Server UND keiner aktiven Verwarnung; Konto-Alter zählt nicht
(außer: neues Konto = riskant); "high" (Strict) wird nie gelockert.
"""
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Stubs für risk.py ────────────────────────────────────────────────────────
for name in ("assets", "assets.message", "assets.data", "assets.trust", "assets.message.warnings"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["assets"].__path__ = [str(ROOT / "assets")]
sys.modules["assets.message"].__path__ = [str(ROOT / "assets" / "message")]
sys.modules["assets.message.warnings"].get_warnings = lambda g, u: []
sys.modules["assets.trust"].get_flag = lambda u: None
sys.modules["assets.data"].load_data = lambda g, k: {}
spec = importlib.util.spec_from_file_location("risk_under_test", ROOT / "assets/moderation/risk.py")
risk = importlib.util.module_from_spec(spec); sys.modules["risk_under_test"] = risk; spec.loader.exec_module(risk)
S = risk.RiskSignals

fails = 0


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    fails += not cond


check("altes Konto, nie im Server gesehen (unbekannt): nicht vertrauenswürdig", not S(account_age_days=2000).is_trusted)
check("altes Konto, erst 3 Tage im Server: nicht vertrauenswürdig", not S(account_age_days=2000, member_days=3).is_trusted)
check("29 Tage im Server: noch nicht vertrauenswürdig", not S(account_age_days=500, member_days=29).is_trusted)
check("30 Tage im Server, keine Verwarnung: vertrauenswürdig", S(account_age_days=500, member_days=30).is_trusted)
check("30 Tage im Server, 1 aktive Verwarnung: nicht vertrauenswürdig", not S(member_days=200, warnings=1).is_trusted)
check("2 Verwarnungen: riskant", S(member_days=200, warnings=2).is_risky)
check("neues Konto bleibt riskant", S(account_age_days=2, member_days=60).is_risky)
check("vertrauenswürdig: strictness 0.75", S(member_days=60).strictness == 0.75)
check("normal: strictness 1.0", S(member_days=5).strictness == 1.0)
check("riskant: strictness 1.5", S(member_days=60, warnings=2).strictness == 1.5)
check("Verwarnung entfernt (0 aktiv) = wieder vertrauenswürdig (Entscheidung der Admins)", S(member_days=60, warnings=0).is_trusted)

# ── _level aus der Pipeline ──────────────────────────────────────────────────
share = types.ModuleType("assets.share"); share.admin_log = lambda *a, **k: None; share.phishing_url_list = set()
sys.modules["assets.share"] = share
from assets.message.safetext import pipeline  # noqa: E402

lv = pipeline._level
check("Strict + vertrauenswürdig bleibt Strict", lv({"sensitivity": "high"}, 0.75) == "high")
check("Strict + normal bleibt Strict", lv({"sensitivity": "high"}, 1.0) == "high")
check("Strict + riskant bleibt Strict (höchste Stufe)", lv({"sensitivity": "high"}, 1.5) == "high")
check("Balanced + vertrauenswürdig wird Relaxed", lv({"sensitivity": "medium"}, 0.75) == "low")
check("Balanced + riskant wird Strict", lv({"sensitivity": "medium"}, 1.5) == "high")
check("Relaxed + riskant wird Balanced", lv({"sensitivity": "low"}, 1.5) == "medium")
check("Relaxed + vertrauenswürdig bleibt Relaxed", lv({"sensitivity": "low"}, 0.75) == "low")
print(f"\n{'ALLE OK' if not fails else str(fails) + ' FEHLER'}")
sys.exit(1 if fails else 0)
