"""Code-Security Agent — the SAST specialist (ADR 0019 P2).

The consumer half of the Opengrep pillar: the scan (P1) lands findings in the
SSOT and the board handler files the high/critical ones as cards routed HERE
(``agent_type = code_security_agent``); the finding router dispatches this
specialist to triage each pending card — ground a minimal before/after fix on
the REAL file content at the scanned commit, comment it, advance the card —
and, once a human approves, the same ONE draft-PR engine (``OpenDraftPrUseCase``)
opens the fix as a draft PR with the SAST location pass-through.

Also the operator's interactive repo-risk surface: severity-weighted repo
ranking ("which repo is most vulnerable?"), scan status/history, and the open
SAST findings list — all deterministic reads over the pillar's existing
use cases (no LLM, no new persistence).

Auto-discovered (ADR 0003); the ``code_security_agent.system`` registry prompt
carries the board-processing discipline.
"""

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.infrastructure.adapters.langchain.agents._mixins import (
    WorkspaceContextMixin,
)
from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
    tool,
)
from components.agents.infrastructure.adapters.langchain.tools import (
    code_security_agent as code_security_tools,
)
from components.agents.infrastructure.adapters.langchain.tools import (
    triage_agent as triage_tools,
)


@register_agent(
    "code_security_agent",
    aliases=("code_security", "sast", "sast_agent", "code_scanner"),
)
class CodeSecurityAgent(WorkspaceContextMixin, BaseAgent):
    """Triages SAST findings into grounded code fixes and repo-risk answers."""

    profile = {
        "name": "Code Security Agent",
        "summary": (
            "The SAST specialist for connected repositories: triages Opengrep "
            "code findings into grounded before/after fix suggestions (verified "
            "against the rule, file, and snippet evidence), feeds approved fixes "
            "to the draft-PR loop, and answers repo-risk questions — which repo "
            "is most vulnerable, what did the last scan find, what is still open."
        ),
        "capabilities": [
            "Rank connected repos by severity-weighted vulnerability risk",
            "Report per-repo scan status, provenance, and history",
            "List open SAST findings from the findings SSOT",
            "Triage a pending code finding with a grounded before/after fix",
            "Open a draft PR for an approved fix (human-gated)",
        ],
        "sample_prompts": [
            "Which of our repos is most vulnerable right now?",
            "Triage the pending code-security findings on the board",
            "What did the last scan of wanjala-dev/api-v0.2.0 find?",
        ],
    }

    @tool(
        name="rank_repos_by_risk",
        description=(
            "Rank the workspace's scannable repos by severity-weighted SAST risk "
            "(critical=10, high=5, medium=2, low=1 over each repo's latest scan). "
            "No input. Returns JSON: [{repo, scanned, risk_score, critical, high, "
            "medium, low, total_findings, commit_sha}] — the answer to 'which repo "
            "is most vulnerable'. Repos never scanned rank last with scanned=false."
        ),
        risk=ToolRisk.READ,
    )
    def rank_repos_by_risk(self, input_str: str = "") -> str:
        return code_security_tools.rank_repos_by_risk(self, input_str)

    @tool(
        name="get_repo_scan_status",
        description=(
            "Per-repo scan status for every allowlisted repo: last-scanned "
            "timestamp, status, duration, trigger provenance, whether a scan is "
            "in flight, and the remaining cooldown. No input. Returns JSON rows."
        ),
        risk=ToolRisk.READ,
    )
    def get_repo_scan_status(self, input_str: str = "") -> str:
        return code_security_tools.get_repo_scan_status(self, input_str)

    @tool(
        name="get_scan_history",
        description=(
            "Recent completed scan snapshots (severity counts per scan, newest "
            'first). Input: optional JSON {"repo": "owner/repo"} to filter, or '
            "empty for all repos. Returns JSON rows with per-scan counts."
        ),
        risk=ToolRisk.READ,
    )
    def get_scan_history(self, input_str: str = "") -> str:
        return code_security_tools.get_scan_history(self, input_str)

    @tool(
        name="get_repo_findings",
        description=(
            "Open SAST findings from the findings SSOT. Input: optional JSON "
            '{"repo": "owner/repo", "limit": 20}. Returns JSON: [{finding_id, '
            "severity, rule_id, repo, path, start_line, title}]."
        ),
        risk=ToolRisk.READ,
    )
    def get_repo_findings(self, input_str: str = "") -> str:
        return code_security_tools.get_repo_findings(self, input_str)

    @tool(
        name="list_pending_code_findings",
        description=(
            "List code-security (SAST) findings on the SOC board that have not "
            "been triaged yet. No input. Returns JSON: [{task_id, title, rule_id, "
            "repo, path, start_line, severity}]. Call this first, then "
            "triage_code_finding on each."
        ),
        risk=ToolRisk.READ,
    )
    def list_pending_code_findings(self, input_str: str = "") -> str:
        return code_security_tools.list_pending_code_findings(self, input_str)

    @tool(
        name="search_repo",
        description=(
            "Search the code of a connected repository. Use this to FIND where "
            "this project does something before proposing a fix that depends on "
            "it — where it loads a signing key, builds a query, reads config. "
            'Input: JSON {"repo": "owner/name", "query": "<code or symbol>", '
            '"limit"?: 20}. Returns JSON {hits: [{path, line_number, line}]}. '
            "Zero hits is a real answer: this project has no such symbol, so do "
            "not assume a helper exists. Read-only."
        ),
        risk=ToolRisk.READ,
    )
    def search_repo(self, input_str: str) -> str:
        return code_security_tools.search_repo(self, input_str)

    @tool(
        name="read_repo_file",
        description=(
            "Read one file from a connected repository at a given ref. Use after "
            "search_repo or list_repo_tree to see the real code you are fixing — "
            "the imports, the surrounding function, how the value reaches the "
            'sink. Input: JSON {"repo": "owner/name", "path": "path/to/file.py", '
            '"ref"?: "<sha or branch>"}. Long files are truncated. Read-only.'
        ),
        risk=ToolRisk.READ,
    )
    def read_repo_file(self, input_str: str) -> str:
        return code_security_tools.read_repo_file(self, input_str)

    @tool(
        name="list_repo_tree",
        description=(
            "List file paths in a connected repository, to learn the project's "
            'layout. Input: JSON {"repo": "owner/name", "ref"?: "<sha>", '
            '"prefix"?: "components/identity"}. Prefer search_repo when you know '
            "what you are looking for; use this to orient. Read-only."
        ),
        risk=ToolRisk.READ,
    )
    def list_repo_tree(self, input_str: str) -> str:
        return code_security_tools.list_repo_tree(self, input_str)

    @tool(
        name="triage_code_finding",
        description=(
            "Triage one pending code-security finding: ground a minimal fix "
            "(before/after snippet) on the real file at the scanned commit, post "
            "it as a comment on the card, and move the card into the Triage "
            'column. Input: JSON {"task_id": "<id>"} (or the bare task_id). '
            "Reversible — safe for autonomous runs."
        ),
        risk=ToolRisk.REVERSIBLE_WRITE,
    )
    def triage_code_finding(self, input_str: str) -> str:
        return code_security_tools.triage_code_finding(self, input_str)

    @tool(
        name="open_draft_pr",
        description=(
            "Open a DRAFT pull request that patches the file flagged by a triaged "
            "code-security finding. Requires an installed VCS connection (with "
            "the repo on its allowlist) AND the open_draft_pr capability enabled. "
            "Only works on findings that are already triaged; an ungrounded or "
            "low-confidence fix still opens, labeled [UNVERIFIED] for careful "
            "human review; at most a few SAST draft PRs may be open per "
            "repo at once (merge rate over PR count). Irreversible tier: needs "
            "explicit human approval; autonomous runs are denied and must surface "
            'the finding instead. Input: JSON {"task_id": "<id>", "repo": '
            '"<owner/repo>" (optional)}.'
        ),
        risk=ToolRisk.IRREVERSIBLE,
    )
    def open_draft_pr(self, input_str: str) -> str:
        return triage_tools.open_draft_pr(self, input_str)
