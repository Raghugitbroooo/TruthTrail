import json
import os
import subprocess
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
EVIDENCE_FILE = PROJECT_DIR / "reports" / "incident_evidence.json"
REPORT_FILE = PROJECT_DIR / "reports" / "incident_report.md"

LOCAL_APP_DATA = Path(
    os.environ.get(
        "LOCALAPPDATA",
        str(Path.home() / "AppData" / "Local"),
    )
)

OLLAMA_EXE = LOCAL_APP_DATA / "Programs" / "Ollama" / "ollama.exe"
MODEL = "qwen3:4b"


def build_prompt(evidence):
    """Create a short prompt from calculated evidence."""
    lines = []

    for incident in evidence.get("incidents", []):
        lines.append(
            f"Dates: {incident.get('previous_date')} to "
            f"{incident.get('current_date')}"
        )
        lines.append(
            f"Revenue: {incident.get('previous_revenue')} to "
            f"{incident.get('current_revenue')}"
        )
        lines.append(
            f"Absolute change: {incident.get('absolute_change')}; "
            f"percentage change: {incident.get('percentage_change')}%"
        )

        contributors = incident.get(
            "largest_product_contributors", []
        )

        for item in contributors[:4]:
            lines.append(
                f"Product {item.get('product')}: "
                f"{item.get('revenue_change'):+,.2f}"
            )

        lines.append("")

    facts = "\n".join(lines)

    return f"""
/no_think

Write a concise Markdown business incident report.
Return ONLY the final report. Do not describe your reasoning.

Include:
- Summary of detected revenue changes.
- Measured changes and leading product contributors.
- Recommended checks for an investigator.
- Limitations and uncertainty.

Rules:
- Use only the supplied figures.
- Do not invent a cause.
- Product changes are contributors, not proven causes.
- No currency is specified. Do not use currency symbols.
- Keep the report under 150 words.

Calculated evidence:
{facts}

Limitations:
{json.dumps(evidence.get("limitations", []))}
"""


def looks_like_reasoning(text):
    """Reject obvious internal reasoning instead of saving it."""
    lower = text.strip().lower()

    suspicious_starts = (
        "okay, the user",
        "the user wants me",
        "we are given",
        "let me go through",
        "let me break this down",
        "steps:",
        "i need to write",
        "we need to",
    )

    return (
        not lower
        or len(lower) < 40
        or lower.startswith(suspicious_starts)
        or "<think>" in lower
    )


def generate_with_ollama(evidence):
    """Try local AI with a short prompt and a three-minute limit."""
    result = subprocess.run(
        [
            str(OLLAMA_EXE),
            "run",
            MODEL,
            "--hidethinking",
            build_prompt(evidence),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or "Ollama returned an error."
        )

    report = result.stdout.strip()

    if looks_like_reasoning(report):
        raise RuntimeError(
            "The model returned reasoning instead of a final report."
        )

    return report


def build_evidence_report(evidence):
    """Create a deterministic report when local AI cannot respond."""
    lines = [
        "# TruthTrail Revenue Anomaly Report",
        "",
        "## Summary",
        "",
        (
            f"TruthTrail recorded {len(evidence.get('incidents', []))} "
            "potential revenue anomalies. These alerts require "
            "investigation and do not establish their causes."
        ),
        "",
        "## Measured changes",
        "",
    ]

    incidents = evidence.get("incidents", [])

    for index, incident in enumerate(incidents, start=1):
        percentage = incident.get("percentage_change")
        percentage_text = (
            f"{percentage:+.2f}%"
            if percentage is not None
            else "not calculable"
        )

        lines.extend([
            f"### Incident {index}: "
            f"{incident.get('previous_date')} to "
            f"{incident.get('current_date')}",
            "",
            (
                f"- Revenue: {incident.get('previous_revenue'):,.2f} "
                f"to {incident.get('current_revenue'):,.2f} "
                "revenue units."
            ),
            (
                f"- Absolute change: "
                f"{incident.get('absolute_change'):+,.2f}."
            ),
            f"- Percentage change: {percentage_text}.",
            "",
            "**Largest product-level contributors:**",
            "",
        ])

        for item in incident.get(
            "largest_product_contributors", []
        )[:4]:
            lines.append(
                f"- {item.get('product')}: "
                f"{item.get('revenue_change'):+,.2f}"
            )

        lines.append("")

    lines.extend([
        "## Recommended investigation",
        "",
        "- Verify the underlying transactions and payment statuses.",
        "- Check data completeness for the affected dates.",
        "- Review the largest product-level changes.",
        "",
        "## Limitations",
        "",
    ])

    for limitation in evidence.get("limitations", []):
        lines.append(f"- {limitation}")

    lines.extend([
        "- The dataset is too small to establish reliable long-term patterns.",
        "- Product-level contributions do not prove causation.",
        "",
        "_Report generated from calculated evidence by TruthTrail._",
    ])

    return "\n".join(lines)


def main():
    if not EVIDENCE_FILE.exists():
        print("Evidence file not found.")
        print("Run python incident_evidence.py first.")
        raise SystemExit(1)

    evidence = json.loads(
        EVIDENCE_FILE.read_text(encoding="utf-8")
    )

    if not OLLAMA_EXE.exists():
        reason = "Ollama executable was not found."
        report = build_evidence_report(evidence)
        source = "Python evidence-based fallback"

    else:
        try:
            print("Trying local AI with a shorter prompt...")
            report = generate_with_ollama(evidence)
            source = "Local Qwen3 AI"

        except (
            OSError,
            RuntimeError,
            subprocess.TimeoutExpired,
        ) as error:
            reason = str(error)
            report = build_evidence_report(evidence)
            source = "Python evidence-based fallback"

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(report + "\n", encoding="utf-8")

    print("\nTruthTrail - Incident Report")
    print("-" * 40)
    print(f"Report source: {source}")

    if source != "Local Qwen3 AI":
        print(f"Reason: {reason}")

    print()
    print(report)
    print(f"\nReport saved to: {REPORT_FILE}")


if __name__ == "__main__":
    main()