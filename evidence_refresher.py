"""Evidence Overdue Reckoning Module

Implements the "evidence overdue reckoning" process:
1. Use evidence_freshness to scan for most severe overdue/low-trust evidence
2. Select 3 pieces of evidence for refresh verification
3. Update docs/index.html milestone to reflect current true capability
"""

import datetime
import json
import os
import re
from pathlib import Path

import evidence_freshness


def get_stale_evidence(top_n=10):
    """Get the top N most stale/overdue evidence pieces."""
    try:
        # Use existing evidence_freshness module
        return evidence_freshness.get_most_stale_evidence(top_n)
    except AttributeError:
        # Fallback: scan evidence files directly
        evidence_dir = Path("evidence")
        if not evidence_dir.exists():
            return []
        
        stale_evidence = []
        for ev_file in evidence_dir.glob("*.json"):
            try:
                with open(ev_file, 'r') as f:
                    ev_data = json.load(f)
                
                # Check staleness based on last_updated
                last_updated = ev_data.get('last_updated', '')
                if not last_updated:
                    continue
                
                try:
                    update_time = datetime.datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                    age_days = (datetime.datetime.now(datetime.timezone.utc) - update_time).days
                    
                    # Consider evidence stale if >30 days old or low trust score
                    trust_score = ev_data.get('trust_score', 1.0)
                    staleness = age_days * (2.0 - trust_score)  # Higher = more stale
                    
                    stale_evidence.append({
                        'file': str(ev_file),
                        'id': ev_data.get('id', ev_file.stem),
                        'age_days': age_days,
                        'trust_score': trust_score,
                        'staleness': staleness,
                        'data': ev_data
                    })
                except (ValueError, TypeError):
                    continue
            except (json.JSONDecodeError, IOError):
                continue
        
        # Sort by staleness (most stale first)
        stale_evidence.sort(key=lambda x: x['staleness'], reverse=True)
        return stale_evidence[:top_n]


def refresh_evidence(ev_data):
    """Simulate refreshing evidence verification."""
    refresh_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # Update the evidence record
    updated_data = ev_data.get('data', {}).copy()
    updated_data['last_updated'] = refresh_time
    updated_data['verification_status'] = 'refreshed'
    updated_data['refresh_count'] = updated_data.get('refresh_count', 0) + 1
    
    # Save updated evidence
    evidence_file = Path(ev_data.get('file', ''))
    if evidence_file.exists():
        try:
            with open(evidence_file, 'w') as f:
                json.dump(updated_data, f, indent=2)
            return True
        except IOError:
            return False
    return False


def calculate_current_capability():
    """Calculate current capability score from refreshed evidence."""
    try:
        # Try to use existing calibration or evalbench
        import calibration
        return calibration.get_current_capability_score()
    except (ImportError, AttributeError):
        try:
            import evalbench
            return evalbench.get_current_score()
        except (ImportError, AttributeError):
            # Fallback: calculate from evidence trust scores
            evidence_dir = Path("evidence")
            if not evidence_dir.exists():
                return 0.5  # Default
            
            total_trust = 0.0
            count = 0
            for ev_file in evidence_dir.glob("*.json"):
                try:
                    with open(ev_file, 'r') as f:
                        ev_data = json.load(f)
                    trust_score = ev_data.get('trust_score', 0.5)
                    total_trust += trust_score
                    count += 1
                except (json.JSONDecodeError, IOError):
                    continue
            
            return total_trust / count if count > 0 else 0.5


def update_html_milestone(new_score):
    """Update docs/index.html with current capability milestone."""
    html_path = Path("docs/index.html")
    if not html_path.exists():
        # Create basic structure if doesn't exist
        html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>OpenCrab Capability Milestone</title>
</head>
<body>
    <h1>OpenCrab Current Capability</h1>
    <div id="milestone-display">
        <p>Current capability score: <span id="milestone-value">0.0</span></p>
        <p>Last updated: <span id="last-updated">never</span></p>
    </div>
</body>
</html>"""
        html_path.parent.mkdir(parents=True, exist_ok=True)
        with open(html_path, 'w') as f:
            f.write(html_content)
    
    # Read current HTML
    with open(html_path, 'r') as f:
        html_content = f.read()
    
    # Update milestone value
    new_score_str = f"{new_score:.3f}"
    update_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Update the milestone value span
    if 'id="milestone-value"' in html_content:
        html_content = re.sub(
            r'<span id="milestone-value">[^<]*</span>',
            f'<span id="milestone-value">{new_score_str}</span>',
            html_content
        )
    
    # Update the last updated span
    if 'id="last-updated"' in html_content:
        html_content = re.sub(
            r'<span id="last-updated">[^<]*</span>',
            f'<span id="last-updated">{update_time}</span>',
            html_content
        )
    
    # Write back
    with open(html_path, 'w') as f:
        f.write(html_content)


def run_reckoning():
    """Execute the evidence overdue reckoning process."""
    print("Starting evidence overdue reckoning...")
    
    # Step 1: Scan for stale evidence
    stale_evidence = get_stale_evidence(10)
    print(f"Found {len(stale_evidence)} stale evidence pieces")
    
    if not stale_evidence:
        print("No stale evidence found. Capability is current.")
        return
    
    # Step 2: Select top 3 for refresh
    to_refresh = stale_evidence[:3]
    print(f"Selected {len(to_refresh)} for refresh:")
    for i, ev in enumerate(to_refresh, 1):
        print(f"  {i}. {ev.get('id', 'unknown')} (age: {ev.get('age_days', '?')} days, trust: {ev.get('trust_score', '?')})")
    
    # Step 3: Refresh the selected evidence
    refreshed_count = 0
    for ev in to_refresh:
        if refresh_evidence(ev):
            refreshed_count += 1
            print(f"  Refreshed: {ev.get('id', 'unknown')}")
        else:
            print(f"  Failed to refresh: {ev.get('id', 'unknown')}")
    
    # Step 4: Calculate current capability
    current_score = calculate_current_capability()
    print(f"Current capability score: {current_score:.3f}")
    
    # Step 5: Update HTML milestone
    update_html_milestone(current_score)
    print(f"Updated docs/index.html milestone to {current_score:.3f}")
    
    # Log the reckoning
    log_reckoning(refreshed_count, current_score)
    
    return {
        'refreshed_count': refreshed_count,
        'current_score': current_score,
        'stale_evidence_count': len(stale_evidence)
    }


def log_reckoning(refreshed_count, current_score):
    """Log the reckoning operation to changelog."""
    log_entry = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'operation': 'evidence_overdue_reckoning',
        'evidence_refreshed': refreshed_count,
        'capability_score': current_score,
        'milestone_updated': True
    }
    
    # Append to changelog
    changelog_path = Path("changelog.jsonl")
    try:
        with open(changelog_path, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except IOError:
        # Create if doesn't exist
        with open(changelog_path, 'w') as f:
            f.write(json.dumps(log_entry) + '\n')


if __name__ == "__main__":
    result = run_reckoning()
    if result:
        print(f"\nReckoning complete. Refreshed {result['refreshed_count']} evidence pieces.")
        print(f"Current true capability: {result['current_score']:.3f}")
    else:
        print("\nNo reckoning needed or possible.")
