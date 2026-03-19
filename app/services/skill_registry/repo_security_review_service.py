from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.services.skill_registry.evidence_pack import EvidencePack
from app.services.skill_registry.parsers.base import RepoContext

logger = logging.getLogger(__name__)

_TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".sh",
}
_TEXT_FILENAMES = {"Dockerfile", "Makefile", "README", "README.md", "SKILL.md"}
_URL_RE = re.compile(r"https?://[^\s\"'()<>]+", re.IGNORECASE)
_DECISION_SCORE = {"approve": 0, "needs_admin_review": 1, "reject": 2}
_RISK_SCORE = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_RULES = (
    {
        "rule_id": "destructive.delete",
        "severity": "high",
        "category": "destructive_actions",
        "message": "Repository deletes files or directories programmatically.",
        "pattern": re.compile(r"shutil\.rmtree\(|os\.(remove|unlink)\(|\.unlink\(", re.IGNORECASE),
    },
    {
        "rule_id": "destructive.shell",
        "severity": "critical",
        "category": "destructive_actions",
        "message": "Repository shells out to potentially destructive system commands.",
        "pattern": re.compile(
            r"rm\s+-rf|subprocess\.(run|Popen|call)\(|powershell|schtasks|systemctl|crontab", re.IGNORECASE
        ),
    },
    {
        "rule_id": "network.external_calls",
        "severity": "medium",
        "category": "privacy_risks",
        "message": "Repository performs outbound HTTP or webhook calls.",
        "pattern": re.compile(
            r"requests\.(get|post|put)|httpx\.(get|post|put)|urllib\.request|fetch\(|axios\.(get|post|put)|webhook",
            re.IGNORECASE,
        ),
    },
    {
        "rule_id": "telemetry.analytics",
        "severity": "medium",
        "category": "privacy_risks",
        "message": "Repository references telemetry or analytics endpoints.",
        "pattern": re.compile(r"telemetry|analytics|segment|mixpanel|posthog|sentry", re.IGNORECASE),
    },
    {
        "rule_id": "sensitive.env_access",
        "severity": "high",
        "category": "privacy_risks",
        "message": "Repository reads environment variables or host secrets.",
        "pattern": re.compile(r"os\.(environ|getenv)|process\.env|\.env|secret|token|api[_-]?key", re.IGNORECASE),
    },
    {
        "rule_id": "sensitive.user_data",
        "severity": "high",
        "category": "privacy_risks",
        "message": "Repository references sensitive local user data sources.",
        "pattern": re.compile(
            r"\.ssh|cookies?|clipboard|localStorage|sessionStorage|keychain|credential", re.IGNORECASE
        ),
    },
)


class RepoSecurityReviewService:
    async def review_repo(
        self,
        repo_context: RepoContext,
        evidence: EvidencePack,
        manifest: dict[str, Any],
        *,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        static_review = _run_static_scan(repo_context.root_path, repo_context.file_index)
        prompt = _build_prompt(repo_context, evidence, manifest, static_review)
        llm_review = None
        try:
            from app.services.providers.llm import llm_service

            response = await llm_service.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1400,
                user_id=user_id,
                tenant_id=user_id,
                api_key_id=user_id,
            )
            llm_review = _normalize_llm_review(_parse_json_response(str(response)))
        except Exception as exc:
            logger.warning("repo_security_review_llm_failed: %s", exc)

        return _merge_reviews(static_review, llm_review)


def _run_static_scan(root_path: Path, file_index: list[str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    network_targets: set[str] = set()
    destructive_actions: set[str] = set()
    privacy_risks: set[str] = set()
    for rel_path in file_index[:120]:
        file_path = root_path / rel_path
        if not file_path.is_file() or not _is_probably_text(file_path):
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")[:16000]
        except Exception as exc:
            logger.debug("repo_security_review_read_failed %s: %s", rel_path, exc)
            continue
        for url in _URL_RE.findall(content):
            network_targets.add(url)
        for rule in _RULES:
            match = rule["pattern"].search(content)
            if not match:
                continue
            findings.append(
                {
                    "source": "static",
                    "rule_id": rule["rule_id"],
                    "severity": rule["severity"],
                    "category": rule["category"],
                    "file": rel_path,
                    "message": rule["message"],
                    "excerpt": _excerpt_around_match(content, match.start(), match.end()),
                }
            )
            if rule["category"] == "destructive_actions":
                destructive_actions.add(rel_path)
            if rule["category"] == "privacy_risks":
                privacy_risks.add(rel_path)
    risk_level = _max_risk([item["severity"] for item in findings])
    decision = "approve"
    if risk_level in {"high", "critical"}:
        decision = "reject" if risk_level == "critical" else "needs_admin_review"
    elif risk_level == "medium":
        decision = "needs_admin_review"
    summary = (
        "Static scan found no obvious destructive or exfiltration patterns."
        if not findings
        else f"Static scan found {len(findings)} potentially risky pattern(s)."
    )
    return {
        "source": "static",
        "decision": decision,
        "risk_level": risk_level,
        "summary": summary,
        "findings": findings,
        "network_targets": sorted(network_targets)[:20],
        "destructive_actions": sorted(destructive_actions),
        "privacy_risks": sorted(privacy_risks),
        "requires_admin_review": decision != "approve",
    }


def _build_prompt(
    repo_context: RepoContext, evidence: EvidencePack, manifest: dict[str, Any], static_review: dict[str, Any]
) -> str:
    readme = (evidence.readme or "").strip()[:3000]
    files = ", ".join(repo_context.file_index[:60]) or "none"
    findings = json.dumps(static_review.get("findings", [])[:8], ensure_ascii=False)
    permissions = json.dumps(manifest.get("permissions") or [], ensure_ascii=False)
    return f"""
You are reviewing a Deeting plugin repository before it can appear in the official plugin market.
Assess whether the code could harm a user's machine, silently exfiltrate data, abuse permissions, or behave differently than its manifest implies.

Return ONLY valid JSON with this exact shape:
{{
  "decision": "approve|needs_admin_review|reject",
  "risk_level": "low|medium|high|critical",
  "summary": "short summary",
  "findings": [{{"severity":"low|medium|high|critical","category":"destructive_actions|privacy_risks|permission_mismatch","message":"...","file":"optional/path"}}],
  "network_targets": ["https://..."],
  "destructive_actions": ["path/or/behavior"],
  "privacy_risks": ["path/or/behavior"]
}}

Review priorities:
1. File deletion, shell execution, persistence, package installs, startup modification.
2. Reading user secrets, cookies, clipboard, SSH keys, env vars, or local documents.
3. Sending user data or telemetry to remote APIs/webhooks.
4. Manifest permission mismatch or behavior that exceeds what a reasonable user would expect.

Repository: {repo_context.repo_url}@{repo_context.revision}
Manifest permissions: {permissions}
Files: {files}
Static findings: {findings}
README:
{readme or "none"}
""".strip()


def _merge_reviews(static_review: dict[str, Any], llm_review: dict[str, Any] | None) -> dict[str, Any]:
    if llm_review is None:
        merged = dict(static_review)
        merged["llm_review_status"] = "fallback_static_only"
        return merged
    findings = list(static_review.get("findings", [])) + list(llm_review.get("findings", []))
    decision = max(
        [static_review.get("decision", "approve"), llm_review.get("decision", "approve")],
        key=lambda item: _DECISION_SCORE.get(str(item), 0),
    )
    risk_level = _max_risk([static_review.get("risk_level", "low"), llm_review.get("risk_level", "low")])
    return {
        "decision": decision,
        "risk_level": risk_level,
        "summary": llm_review.get("summary") or static_review.get("summary"),
        "findings": findings,
        "network_targets": _dedupe(static_review.get("network_targets", []) + llm_review.get("network_targets", [])),
        "destructive_actions": _dedupe(
            static_review.get("destructive_actions", []) + llm_review.get("destructive_actions", [])
        ),
        "privacy_risks": _dedupe(static_review.get("privacy_risks", []) + llm_review.get("privacy_risks", [])),
        "requires_admin_review": decision != "approve",
        "llm_review_status": "ok",
    }


def _normalize_llm_review(payload: dict[str, Any]) -> dict[str, Any]:
    decision = str(payload.get("decision") or "needs_admin_review").strip() or "needs_admin_review"
    risk_level = str(payload.get("risk_level") or "medium").strip() or "medium"
    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
    return {
        "decision": decision if decision in _DECISION_SCORE else "needs_admin_review",
        "risk_level": risk_level if risk_level in _RISK_SCORE else "medium",
        "summary": str(payload.get("summary") or "LLM review flagged potential security issues.").strip(),
        "findings": [item for item in findings if isinstance(item, dict)],
        "network_targets": [str(item) for item in payload.get("network_targets") or [] if item],
        "destructive_actions": [str(item) for item in payload.get("destructive_actions") or [] if item],
        "privacy_risks": [str(item) for item in payload.get("privacy_risks") or [] if item],
    }


def _parse_json_response(response: str) -> dict[str, Any]:
    text = response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise RuntimeError("security review must return a JSON object")
    return payload


def _is_probably_text(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_EXTENSIONS or path.name in _TEXT_FILENAMES


def _excerpt_around_match(content: str, start: int, end: int) -> str:
    left = max(0, start - 60)
    right = min(len(content), end + 120)
    return " ".join(content[left:right].split())[:220]


def _max_risk(levels: list[str]) -> str:
    return max((str(level or "low") for level in levels), key=lambda item: _RISK_SCORE.get(item, 0), default="low")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result[:20]
