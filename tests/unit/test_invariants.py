"""CLAIM-LINT — the mechanical guards for the bug class that kept escaping this repo (GOAL-prove-it P0.2).

Three real, shipped bugs motivated each guard below. Every one passed the entire unit + integration suite
and a manual "live-verified" run, because a prose CLAIM was never mechanically checked:

  1. "#4: every lineage publish is staged through the outbox" — THREE publishers bypassed it (the media
     head + two FAIL emits, one on a _DROP path where a lost publish erased the failure forever). I had
     verified the ONE publisher I changed and never grepped for the rest.
  2. "MEDALLION_LINEAGE_OUTBOX_URI is wired" — the chart injected it and no code ever read it (a dead env).
     A whole feature was configured and inert.
  3. "seed_warehouse grants the FGA parent edge" — it wrote `warehouse#parent`, a relation the warehouse
     type does NOT define (its pointer is `project`). OpenFGA rejected the write → a live 503, while every
     unit test stayed green because mocked `fga.check`/`write_tuples` pin the STRING, never the SCHEMA.

The rule these encode: a claim that cannot be proven by a grep, a test, or a render is not a claim — it is
a guess. Each test below fails on the ORIGINAL buggy code and passes now.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SERVICES = REPO / "services"
CHART = REPO / "chart"


# --------------------------------------------------------------------------------------------------
# 1. #4 outbox uniformity — zero bare publishes to the LINEAGE topic
# --------------------------------------------------------------------------------------------------


def _bare_lineage_publishes() -> list[str]:
    """Every `dapr_publish.publish_event(...)` whose topic_name is `settings.lineage_topic`.

    A lineage event MUST go through `outbox.publish_lineage_with_outbox` (stage → publish → drop) so a
    crash between the Lance commit and the publish ack leaves the event recoverable. A bare publish is
    the exact commit→publish loss window #4 exists to close. TRIGGER topics (pub_topic / media_topic /
    raw_topic / train_topic) are correctly bare: the outbox re-ingests lineage, it never re-fires triggers.
    """
    offenders: list[str] = []
    for py in SERVICES.rglob("*.py"):
        lines = py.read_text().splitlines()
        for i, line in enumerate(lines):
            if "dapr_publish.publish_event(" not in line:
                continue
            # the topic kwarg sits within the call's next few lines
            window = "\n".join(lines[i : i + 8])
            if "topic_name=settings.lineage_topic" in window:
                offenders.append(f"{py.relative_to(REPO)}:{i + 1}")
    return offenders


def test_every_lineage_publish_goes_through_the_outbox() -> None:
    offenders = _bare_lineage_publishes()
    assert not offenders, (
        "#4 claims 'every lineage publish is staged', but these publish to the LINEAGE topic WITHOUT the "
        f"outbox — a crash after the Lance commit loses the event forever: {offenders}. "
        "Use outbox.publish_lineage_with_outbox(...). (Trigger topics may stay bare.)"
    )


# --------------------------------------------------------------------------------------------------
# 2. No dead config — every env var the chart injects is actually READ by some service
# --------------------------------------------------------------------------------------------------

# Envs consumed by a THIRD-PARTY container's own binary, never by first-party code. Each entry is a
# server we deploy but did not write (RustFS/OpenBao/Postgres/NATS/Dapr/OTel/Greptime/Vector/Ray/OpenFGA),
# so its absence from our source proves nothing. Anything NOT matching here is OURS and must be read.
_THIRD_PARTY_ENV = re.compile(
    r"^(DAPR_|OTEL_|PYTHON|PATH$|HOME$|BAO_|VAULT_|POSTGRES_|PG|NATS_|AWS_|RUSTFS_|RUST_|GREPTIME|"
    r"VECTOR_|OPENFGA_|RAY_|MINIO_|S3_|TZ$|LANG$|LC_|UV_|VIRTUAL_ENV)"
)


def _chart_injected_envs() -> set[str]:
    envs: set[str] = set()
    for tpl in (CHART / "templates").rglob("*.yaml"):
        for m in re.finditer(r"name:\s*([A-Z][A-Z0-9_]{3,})\b", tpl.read_text()):
            name = m.group(1)
            if not _THIRD_PARTY_ENV.match(name):
                envs.add(name)
    return envs


def _first_party_source() -> str:
    """ALL first-party source — python services AND the SvelteKit frontend.

    Deliberately wider than services/: the BFF reads LINEAGE_API in TypeScript, so a services-only search
    would call a live, load-bearing env "dead". Searching every first-party file makes the guard STRONGER
    (it now covers the frontend too) rather than weaker. Pydantic reads envs via alias="FOO", so a plain
    substring match over source is the right check — not os.environ lookups.
    """
    parts = [p.read_text(errors="ignore") for p in SERVICES.rglob("*.py")]
    fe = REPO / "frontend"
    if fe.exists():
        for ext in ("*.ts", "*.svelte", "*.js"):
            parts += [
                p.read_text(errors="ignore")
                for p in fe.rglob(ext)
                if "node_modules" not in p.parts and ".svelte-kit" not in p.parts
            ]
    return "\n".join(parts)


def test_no_dead_chart_env_vars() -> None:
    """A chart-injected env that NO first-party code reads = a feature configured but INERT.

    This is exactly how MEDALLION_LINEAGE_OUTBOX_URI shipped: the chart set it, the producer never read
    it, and the outbox silently did nothing on that path while the docs claimed coverage. The feature was
    fully "configured" and completely dead.
    """
    source = _first_party_source()
    dead = sorted(env for env in _chart_injected_envs() if env not in source)
    assert not dead, (
        f"the chart injects these env vars but NO first-party code reads them (dead config → a feature "
        f"that is configured but inert): {dead}. Either wire them up or delete them from the chart."
    )


# --------------------------------------------------------------------------------------------------
# 3. FGA schema contract — every relation the code WRITES or CHECKS must exist on that type
# --------------------------------------------------------------------------------------------------


def _model_relations() -> dict[str, set[str]]:
    model = json.loads((SERVICES / "common/auth/model.json").read_text())
    return {t["type"]: set(t.get("relations") or {}) for t in model["type_definitions"]}


def _fga_literals() -> list[tuple[str, str, str]]:
    """(file:line, object_type, relation) for every literal FGA (type, relation) pair in the code.

    Catches the `warehouse#parent` class: a mocked `fga.check`/`write_tuples` asserts the STRING that was
    passed, never that the relation EXISTS on the type — so a phantom relation sails through every unit
    test and only fails at runtime, as an OpenFGA rejection (a fail-closed 503 for every caller).
    """
    found: list[tuple[str, str, str]] = []
    # relation="X", ... obj=f"type:{...}"  /  ClientTuple(relation="X", object=f"type:...")
    rel_re = re.compile(r'relation=["\']([a-z_]+)["\']')
    obj_re = re.compile(r'(?:obj|object)=f?["\']([a-z_]+):')
    for py in SERVICES.rglob("*.py"):
        lines = py.read_text().splitlines()
        for i, line in enumerate(lines):
            rel = rel_re.search(line)
            if not rel:
                continue
            window = "\n".join(lines[max(0, i - 4) : i + 5])
            for obj in obj_re.finditer(window):
                found.append((f"{py.relative_to(REPO)}:{i + 1}", obj.group(1), rel.group(1)))
    return found


def test_every_fga_relation_in_code_exists_in_the_compiled_model() -> None:
    model = _model_relations()
    phantom = [
        f"{loc} -> {obj_type}#{rel}"
        for loc, obj_type, rel in _fga_literals()
        if obj_type in model and rel not in model[obj_type]
    ]
    assert not phantom, (
        "the code writes/checks FGA relations that do NOT exist on that type in the compiled model.json — "
        f"OpenFGA REJECTS these at runtime (fail-closed 503 for every caller): {phantom}"
    )


def test_every_first_party_deployment_is_hardened() -> None:
    """The docs claim "every Deployment has probes + preStop". The gateway had NEITHER (audit 2026-07-14).

    An "every" claim in prose is worth nothing; this loop is what makes it true. It renders the chart and
    checks each FIRST-PARTY Deployment (third-party subcharts — dapr/nats/openfga/dex — are not ours to
    template). preStop matters most on the gateway: it is the INGRESS, so without a drain delay a rolling
    update drops in-flight requests while kube-proxy is still routing to the terminating pod.
    """
    import shutil
    import subprocess

    helm = shutil.which("helm") or str(REPO / ".localbin/helm")
    if not Path(helm).exists():
        pytest.skip("helm not available")
    rendered = subprocess.run(  # noqa: S603
        [helm, "template", str(CHART)], capture_output=True, text=True, check=True
    ).stdout

    first_party = (
        "gateway", "catalog", "lineage", "compaction", "lance-ray",
        "raw-to-bronze", "bronze-to-silver", "silver-to-gold", "media-to-silver", "web",
    )  # fmt: skip
    unhardened: list[str] = []
    for doc in rendered.split("\n---"):
        if "kind: Deployment" not in doc:
            continue
        m = re.search(r"^\s*name:\s*(\S+)", doc, re.M)
        name = m.group(1) if m else "?"
        if not any(f in name for f in first_party):
            continue
        missing = [k for k in ("livenessProbe", "readinessProbe", "preStop") if k not in doc]
        if missing:
            unhardened.append(f"{name} missing {missing}")
    assert not unhardened, f"first-party Deployments are not hardened: {unhardened}"


@pytest.mark.parametrize(
    ("obj_type", "relation"),
    [
        # the exact pairs whose absence caused live outages / dead gates
        ("warehouse", "project"),  # the parent pointer (NOT `parent` — that was the 503)
        ("warehouse", "owner"),
        ("project", "can_create_warehouse"),  # the dormant admin gate #3-A finally enforces
        ("namespace", "parent"),
        ("table", "parent"),
    ],
)
def test_load_bearing_relations_are_defined(obj_type: str, relation: str) -> None:
    assert relation in _model_relations()[obj_type], (
        f"{obj_type}#{relation} is load-bearing but missing from the compiled model"
    )


def test_every_helm_set_key_in_our_scripts_exists_in_values() -> None:
    """A `--set` key that does not exist in values.yaml is a SILENT no-op — helm accepts it without a word.

    The bug this encodes (2026-07-14): `scripts/e2e_stack.sh` passed `--set web.enabled=false` to deploy a
    headless stack. There was no `web.enabled` key. Helm shrugged, the web Deployment (which had no `if`
    guard at all) rendered anyway, its image is never built in CI, so it sat in ImagePullBackOff and
    `helm --wait` could never converge. The e2e-stack job — the entire point of P0.1, the job whose whole
    purpose is to stop us shipping unproven claims — therefore FAILED ON EVERY RUN and nobody noticed.

    A flag you *believe* you are setting, that silently sets nothing, is worse than no flag: it makes a
    stack you never actually configured look configured. This asserts every key we --set actually exists.
    """
    import yaml

    values = yaml.safe_load((CHART / "values.yaml").read_text())

    def defined(dotted: str) -> bool:
        node = values
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return True

    # `--set a.b=c` / `--set-json a.b=[...]` / `--set a.b=c,d.e=f` across every script we ship.
    pattern = re.compile(r"--set(?:-json|-string)?[= ]\"?([A-Za-z0-9_.\[\]-]+)=")
    unknown: list[str] = []
    for script in sorted((REPO / "scripts").glob("*.sh")):
        for key in pattern.findall(script.read_text()):
            base = key.split("[")[0]  # list index: catalog.multibase.dataBases[0] -> ...dataBases
            if not defined(base):
                unknown.append(f"{script.name}: --set {key} (no such key in values.yaml)")
    assert not unknown, "helm --set keys that silently do nothing:\n  " + "\n  ".join(unknown)


def test_no_warehouse_bucket_access_bypasses_the_deactivation_gate() -> None:
    """SECURITY INVARIANT (audit #2/#6 + #35 class): reaching a warehouse's isolated bucket connection —
    which happens only via ``_namespace_for_root`` — MUST consult the warehouse's lifecycle status, or a
    handler can provision/read inside a QUARANTINED (deactivated) bucket, bypassing tenant offboarding.

    Today two paths reach a bucket: ``get_namespace`` (through ``_resolve_warehouse_root``'s live status
    gate) and ``create_warehouse_namespace`` (which checks ``record["status"]`` inline). This test fails the
    moment a NEW caller of ``_namespace_for_root`` appears in a module that does not also gate on status —
    exactly the bug the audit found in the namespace-create path.
    """
    # Match the cached wrapper `_namespace_for_root(` but NOT the raw builder `build_namespace_for_root(`
    # (the wrapper's substring lives inside the builder's name) — a word boundary before the underscore.
    caller_re = re.compile(r"(?<![A-Za-z_])_namespace_for_root\(")
    ungated: list[str] = []
    for path in SERVICES.rglob("*.py"):
        text = path.read_text()
        if not caller_re.search(text):
            continue
        # The definition site (dependencies.py) gates via _resolve_warehouse_root; every caller must gate on
        # the warehouse status one way or another before it reaches the bucket.
        gated = (
            "_resolve_warehouse_root" in text
            or "warehouse_status" in text
            or re.search(r'\.get\("status"\)|\["status"\]', text) is not None
        )
        if not gated:
            ungated.append(str(path.relative_to(REPO)))
    assert not ungated, (
        "these modules reach a warehouse bucket via _namespace_for_root WITHOUT a deactivation-status gate "
        f"— a quarantined-warehouse bypass (audit #2/#6): {ungated}"
    )


def test_catalog_authz_primitive_fails_closed_on_openfga_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    """SECURITY INVARIANT (condition 3a): the shared catalog authz primitive ``_require`` — which EVERY
    catalog gate (``authorize`` / ``require_*``) funnels through to ``fga.check`` — must RAISE (fail closed)
    when OpenFGA is unreachable, never swallow the outage and allow. If it failed OPEN, every gated route
    would too. (The lineage read gate's fail-closed is pinned in test_lineage_auth.py.)
    """
    import asyncio
    from unittest.mock import MagicMock

    from catalog.api import fga_deps as cat_fga
    from common import fga as common_fga
    from lance_namespace import ServiceUnavailableError

    async def _outage(*_a: object, **_k: object) -> bool:
        raise ServiceUnavailableError("openfga down")

    monkeypatch.setattr(common_fga, "check", _outage)
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(cat_fga._require(MagicMock(), user="u", relation="can_read_data", obj="table:x"))


def test_authz_decisions_are_audited() -> None:
    """Compliance invariant (#41): the single authz choke point ``fga_deps._require`` must emit an audit
    event, so every governed access decision — allow and deny — lands on the dedicated audit trail. Before
    #41 only denials were logged (to the general logger). Grep-provable so it can never silently regress:
    the moment ``_require`` stops calling ``audit(``, a governed deployment's audit trail goes half-blind."""
    src = (SERVICES / "catalog" / "api" / "fga_deps.py").read_text()
    body = src.split("async def _require(", 1)[1].split("\nasync def ", 1)[0]
    assert "audit(" in body, "_require must emit an audit event for every authz decision (#41 compliance)"


def test_batch_authz_and_credential_vending_are_audited() -> None:
    """Compliance invariant (#41 follow-up): the two authz surfaces that do NOT funnel through ``_require``
    — the batch gate and the credential vend — must emit their own audit events, or their decisions fall
    off the trail exactly the way the pre-#41 code's did. Grep-provable like the ``_require`` guard."""
    fga_src = (SERVICES / "catalog" / "api" / "fga_deps.py").read_text()
    batch = fga_src.split("async def _authorize_batch(", 1)[1].split("\nasync def ", 1)[0]
    assert batch.count("audit(") >= 3, "_authorize_batch must audit table/parent/owner decisions (#41)"
    vend = (SERVICES / "catalog" / "api" / "v1" / "endpoints" / "credentials.py").read_text()
    assert vend.count("audit(") >= 2, "credential vending must audit the write-tier gate + issuance (#41)"


def test_authentication_outcomes_are_audited() -> None:
    """Compliance invariant (#41): ``authenticate`` must audit both the success (who logged in) and the
    failure (rejected token) paths — authn was entirely unlogged before #41, so brute-force / forged-token
    attempts were invisible. Grep-provable: the failure + success audit calls must both remain."""
    src = (SERVICES / "catalog" / "api" / "security.py").read_text()
    assert src.count("audit(") >= 2, "authenticate must audit both success and failure (#41 compliance)"
    assert "SUCCESS" in src and "FAILURE" in src
